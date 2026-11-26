"""Render real costmap footprints through RViz's queued Marker display.

Foxy PolygonDisplay creates Ogre buffers directly on the TF listener thread
when transforms become available. MarkerDisplay queues rendering onto the GUI
thread; no transform, footprint geometry or collision configuration is invented.
"""


def footprint_marker(polygon, namespace):
    from geometry_msgs.msg import Point
    from visualization_msgs.msg import Marker
    marker=Marker();marker.header=polygon.header;marker.ns=namespace;marker.id=0
    marker.type=Marker.LINE_STRIP;marker.pose.orientation.w=1.;marker.scale.x=.025
    marker.color.r=0.;marker.color.g=.67;marker.color.b=1.;marker.color.a=1.
    marker.lifetime.sec=2
    marker.points=[Point(x=float(p.x),y=float(p.y),z=float(p.z)) for p in polygon.polygon.points]
    if marker.points:
        first,last=marker.points[0],marker.points[-1]
        if (first.x,first.y,first.z)!=(last.x,last.y,last.z):marker.points.append(first)
        marker.action=Marker.ADD
    else:marker.action=Marker.DELETE
    return marker


def attach_footprints(node):
    from geometry_msgs.msg import PolygonStamped
    from visualization_msgs.msg import Marker
    publishers=[];subscriptions=[];counts={'local':0,'global':0}
    def forward(message,publisher,label):
        publisher.publish(footprint_marker(message,label));counts[label]+=1
    for name in ('local','global'):
        publisher=node.create_publisher(Marker,'/guidebot/navigation/'+name+'_footprint',10)
        subscription=node.create_subscription(PolygonStamped,'/'+name+'_costmap/published_footprint',
            lambda message,pub=publisher,label=name:forward(message,pub,label),10)
        publishers.append(publisher);subscriptions.append(subscription)
    return publishers,subscriptions,counts
