"""Small read-only point-cloud previews; geometry stays in the source lidar frame."""
import os
from pathlib import Path
import numpy as np


def cloud_preview(message, maximum=4000):
    fields={field.name:field for field in message.fields}
    if any(name not in fields or fields[name].datatype != 7 or fields[name].count != 1
           for name in ('x','y','z')):
        raise ValueError('Preview requires float32 XYZ fields')
    if message.width*message.height == 0:return b''
    if message.row_step < message.width*message.point_step or len(message.data) < message.row_step*message.height:
        raise ValueError('Truncated cloud')
    order='>f4' if message.is_bigendian else '<f4'
    values=[]
    for name in ('x','y','z'):
        offset=fields[name].offset
        if offset < 0 or offset+4 > message.point_step:raise ValueError('Invalid XYZ offset')
        a=np.ndarray((message.height,message.width),dtype=order,buffer=message.data,
                     offset=offset,strides=(message.row_step,message.point_step))
        values.append(a.reshape(-1))
    xyz=np.column_stack(values)
    xyz=xyz[np.all(np.isfinite(xyz),axis=1)]
    if len(xyz)>maximum:xyz=xyz[::int(np.ceil(len(xyz)/maximum))]
    return xyz.astype('<f4').tobytes()


def write_preview(directory,message):
    destination=Path(directory)/'preview.bin';temp=destination.with_suffix('.tmp')
    temp.write_bytes(cloud_preview(message));os.replace(str(temp),str(destination))
