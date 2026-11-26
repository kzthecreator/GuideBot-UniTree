"""Experimental floor-leveled LiDAR mapping, with no ROS/DDS or motor access.

The current floor search is specific to the observed upside-down MID360 mount.
Poses describe a leveled LiDAR frame, NOT robot_center. No base extrinsic is
invented. Projected obstacles are not a certified collision/navigation map.
"""
import json
from pathlib import Path
import struct
import zlib

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation


def voxel(points, size=.08):
    _, indices = np.unique(np.floor(points / size).astype('int32'), axis=0, return_index=True)
    return points[indices]


def level(points, rng):
    """Measure floor; reject unsupported geometry instead of using identity TF."""
    candidates = points[(np.linalg.norm(points[:, :2], axis=1) < 5) &
                        (points[:, 2] > .6) & (points[:, 2] < 2)]
    if len(candidates) < 100:
        raise ValueError('Insufficient floor candidates for this mount')
    best = None
    for _ in range(70):
        sample = candidates[rng.choice(len(candidates), 3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        length = np.linalg.norm(normal)
        if length < 1e-8:
            continue
        normal /= length
        if abs(normal[2]) < .9:
            continue
        mask = np.abs(candidates @ normal - normal @ sample[0]) < .025
        if best is None or np.sum(mask) > np.sum(best):
            best = mask
    if best is None or np.sum(best) < max(100, .25 * len(candidates)):
        raise ValueError('No reliable floor plane')
    center = candidates[best].mean(axis=0)
    _, _, vectors = np.linalg.svd(candidates[best] - center, full_matrices=False)
    normal = vectors[-1]
    normal = normal if normal[2] < 0 else -normal
    height = -normal @ center
    rms = float(np.sqrt(np.mean((candidates[best] @ normal + height) ** 2)))
    if not .6 < height < 2 or rms > .03:
        raise ValueError('Floor fit outside measured mount limits')
    flip = np.diag([1, -1, -1])
    upright = flip @ normal
    axis = np.cross(upright, [0, 0, 1])
    angle = np.arccos(np.clip(upright[2], -1, 1))
    rotation = Rotation.from_rotvec(axis / max(np.linalg.norm(axis), 1e-9) * angle).as_matrix() @ flip
    leveled = points @ rotation.T
    leveled[:, 2] += height
    return leveled, [*normal, height, rms]


def transform(points, pose):
    c, s = np.cos(pose[2]), np.sin(pose[2])
    moved = points.copy()
    moved[:, :2] = points[:, :2] @ np.array([[c, s], [-s, c]]) + pose[:2]
    return moved


def icp(points, reference, guess):
    """Trimmed multi-scale planar ICP. Returns pose and overlap/RMS diagnostics."""
    if min(len(points), len(reference)) < 40:
        raise ValueError('Insufficient obstacle points for registration')
    pose = np.array(guess, dtype=float)
    tree = cKDTree(reference)
    for limit in [.4, .2, .1]:
        for _ in range(15):
            moved = transform(points, pose)
            distances, indices = tree.query(moved)
            mask = distances < limit
            if np.sum(mask) < 40:
                raise ValueError('Registration has too few correspondences')
            a, b = moved[mask, :2], reference[indices[mask], :2]
            ca, cb = a.mean(axis=0), b.mean(axis=0)
            u, _, v = np.linalg.svd((a - ca).T @ (b - cb))
            rotation = v.T @ u.T
            if np.linalg.det(rotation) < 0:
                v[-1] *= -1
                rotation = v.T @ u.T
            angle = np.arctan2(rotation[1, 0], rotation[0, 0])
            translation = cb - rotation @ ca
            pose[:2] = rotation @ pose[:2] + translation
            pose[2] += angle
            if np.linalg.norm(translation) < .0001 and abs(angle) < .0001:
                break
    distances, _ = tree.query(transform(points, pose))
    mask = distances < .15
    return pose, [float(np.mean(mask)), float(np.sqrt(np.mean(distances[mask] ** 2)))]


def write_png(path, pixels):
    """Lossless RGB preview without adding a plotting dependency."""
    height, width, channels = pixels.shape
    assert channels == 3
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b''.join(b'\0' + row.tobytes() for row in pixels.astype('uint8'))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' +
                          chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) +
                          chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def export_grid(directory, scans, poses, resolution=.05):
    """Observed occupied/free/unknown cells; no unobserved region declared free.

    Ray clearing uses nearest projected obstacle per angular bin. Elevated
    projections can hide traversable surfaces; this remains a draft map.
    """
    directory = Path(directory)
    scans = [scan[:, :2] for scan in scans]
    world = [transform(scan, pose) for scan, pose in zip(scans, poses)]
    all_points = np.concatenate(world)
    lower = np.floor((np.minimum(all_points.min(axis=0), poses[:, :2].min(axis=0)) - 1) / resolution) * resolution
    upper = np.maximum(all_points.max(axis=0), poses[:, :2].max(axis=0)) + 1
    width, height = np.ceil((upper - lower) / resolution).astype(int) + 1
    if width * height > 16_000_000:
        raise ValueError('Map exceeds grid memory limit')
    hits = np.zeros((height, width), dtype='uint16')
    free = np.zeros_like(hits, dtype=bool)
    for scan, moved, pose in zip(scans, world, poses):
        cells = np.floor((moved - lower) / resolution).astype(int)
        unique = np.unique(cells, axis=0)
        hits[unique[:, 1], unique[:, 0]] += 1
        angles = np.floor((np.arctan2(scan[:, 1], scan[:, 0]) + np.pi) / (2*np.pi) * 720).astype(int)
        ranges = np.linalg.norm(scan, axis=1)
        order = np.argsort(ranges)
        _, first = np.unique(angles[order], return_index=True)
        start = (pose[:2] - lower) / resolution
        for index in order[first]:
            end = (moved[index] - lower) / resolution
            count = int(np.ceil(np.max(np.abs(end - start)))) + 1
            ray = np.floor(start + np.linspace(0, 1, count, endpoint=False)[:, None] * (end - start)).astype(int)
            # Leave a two-cell margin in front of an obstacle.
            ray = ray[:-2]
            free[ray[:, 1], ray[:, 0]] = True
    grid = np.full((height, width), 205, dtype='uint8')
    grid[free] = 254
    grid[hits >= 3] = 0
    image = grid[::-1]
    (directory/'map.pgm').write_bytes(('P5\n%d %d\n255\n' % (width, height)).encode() + image.tobytes())
    (directory/'map.yaml').write_text('image: map.pgm\nresolution: %s\norigin: [%s, %s, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n' % (resolution, *lower))
    rgb = np.repeat(image[:, :, None], 3, axis=2)
    cells = np.floor((poses[:, :2] - lower) / resolution).astype(int)
    for x, y in cells:
        row = height - 1 - y
        rgb[max(0, row-1):row+2, max(0, x-1):x+2] = [35, 115, 230]
    for (x, y), color in [(cells[0], [0, 180, 70]), (cells[-1], [240, 65, 40])]:
        row = height - 1 - y
        rgb[max(0,row-3):row+4,max(0,x-3):x+4] = color
    write_png(directory/'preview.png', np.repeat(np.repeat(rgb, 2, axis=0), 2, axis=1))
    return dict(resolution_m=resolution, width=int(width), height=int(height), origin=lower.tolist(),
                occupied_cells=int(np.sum(grid == 0)), free_cells=int(np.sum(grid == 254)))


def finalize(directory, capture, extracted, matched):
    """Export measured trajectory/map plus explicit acceptance limits and evidence."""
    directory = Path(directory)
    poses = matched['poses']
    scans = [matched['points'][a:b] for a, b in zip(matched['offsets'][:-1], matched['offsets'][1:])]
    grid = export_grid(directory, scans, poses)
    loop = matched['loop']
    difference = loop - poses[-1]
    difference[2] = np.arctan2(np.sin(difference[2]), np.cos(difference[2]))
    loop_metric = matched['loop_metrics']
    metrics = matched['metrics']
    floor = matched['floors']
    odom = extracted['odom']
    closure_xy = float(np.linalg.norm(difference[:2]))
    consistent = bool(loop_metric[0] >= .6 and loop_metric[1] <= .09 and
                      closure_xy <= .3 and abs(difference[2]) <= .1 and
                      np.min(metrics[:, 0]) >= .6 and np.max(metrics[:, 1]) <= .09)
    summary = dict(
        status='offline_draft_consistent' if consistent else 'offline_draft_needs_review',
        navigation_ready=False, capture=str(capture),
        source_clouds=len(extracted['cloud_times']), matched_clouds=len(poses),
        duration_s=float(np.ptp(extracted['cloud_times'])),
        trajectory_length_m=float(np.linalg.norm(np.diff(poses[:, :2], axis=0), axis=1).sum()),
        odom_endpoint_xy_m=float(np.linalg.norm(odom[-1, 1:3] - odom[0, 1:3])),
        lidar_endpoint_xy_m=float(np.linalg.norm(poses[-1, :2])),
        lidar_endpoint_yaw_deg=float(np.rad2deg(np.arctan2(np.sin(poses[-1, 2]),np.cos(poses[-1, 2])))),
        independent_loop_pose=loop.tolist(), loop_overlap=float(loop_metric[0]),
        loop_inlier_rms_m=float(loop_metric[1]), closure_disagreement_m=closure_xy,
        closure_yaw_disagreement_deg=float(np.rad2deg(abs(difference[2]))),
        local_overlap_min=float(np.min(metrics[:, 0])),
        local_inlier_rms_median_m=float(np.median(metrics[:, 1])),
        local_inlier_rms_max_m=float(np.max(metrics[:, 1])),
        floor_height_median_m=float(np.median(floor[:, 3])),
        floor_rms_p95_m=float(np.percentile(floor[:, 4], 95)),
        grid=grid,
        method='Measured per-frame floor leveling; 3D correspondences, planar ICP; '
               'factory odom relative yaw seeds only; previous 8 scans as local submap; '
               'every third cloud; no forced loop or pose graph correction',
        coordinate_frame='First leveled LiDAR, Z up, floor Z=0; not robot_center',
        obstacle_height_m=[.3, 1.7], range_m=[.5, 12],
        limits=['No calibrated robot_center-to-lidar TF', 'No per-point motion deskew',
                'No localization or navigation acceptance', 'No low obstacles below 0.3m in draft grid',
                'Projected free-space rays do not certify clearance or traversability',
                'ICP residual/overlap are inlier fit statistics, not absolute map accuracy'],
        robot_commands=False, audio_started=False)
    (directory/'report.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    stamps = extracted['cloud_times'][matched['indices']]
    np.savetxt(directory/'trajectory.csv', np.column_stack([stamps-stamps[0],poses]), delimiter=',',
               header='elapsed_s,lidar_x_m,lidar_y_m,lidar_yaw_rad', comments='')
    return summary
