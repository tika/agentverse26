"""Irregular silhouette meshes; conforming rows explicitly follow profile knots."""
import math
import numpy as np
from profiles import drum_profile, radius_at


def outline(rng, width, height, count=64):
    angles=np.arange(count)*2*math.pi/count
    radial=np.ones(count)
    for frequency,weight in ((3,.08),(7,.055),(13,.028),(23,.015)):
        radial += weight*np.sin(angles*frequency+rng.uniform(0,2*math.pi))
    xy=np.column_stack((np.cos(angles)*radial,np.sin(angles)*radial))
    xy[:,0] *= width/np.ptp(xy[:,0]); xy[:,1] *= height/np.ptp(xy[:,1])
    xy -= (xy.max(0)+xy.min(0))/2
    return xy


def surface_mesh(entry, spec):
    rng=np.random.default_rng(spec['mesh_seed'])
    width,height=spec['size']
    polygon=outline(rng,width,height)
    profile=drum_profile(entry['category'])
    z0=spec['z']
    # Contour vertices + 5 mm rows + exact chime/hoop knots keep decals outside steel.
    zs=set(polygon[:,1].tolist())
    zs.update(np.linspace(-height/2,height/2,max(3,math.ceil(height/.005))).tolist())
    zs.update(z-z0 for _,z in profile if z0-height/2 < z < z0+height/2)
    zs=sorted(z for z in zs if 0 <= z+z0 <= entry['height'])
    points,faces,uv=[],[],[]
    columns=32
    for local_z in zs:
        intersections=[]
        for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
            if abs(a[1]-b[1])<1e-12:
                if abs(local_z-a[1])<1e-9: intersections.extend([a[0],b[0]])
            elif min(a[1],b[1])-1e-9 <= local_z <= max(a[1],b[1])+1e-9:
                intersections.append(float(a[0]+(b[0]-a[0])*(local_z-a[1])/(b[1]-a[1])))
        left,right=(min(intersections),max(intersections)) if intersections else (0,0)
        z=local_z+z0
        radius=radius_at(profile,z)+.003
        for j in range(columns+1):
            arc=left+(right-left)*j/columns
            angle=spec['angle']+arc/entry['radius']
            points.append((entry['x']+radius*math.cos(angle),entry['y']+radius*math.sin(angle),z))
    for row in range(len(zs)-1):
        for j in range(columns):
            k=row*(columns+1)+j
            faces.append((k,k+1,k+columns+2,k+columns+1))
            v0,v1=(zs[row]+height/2)/height,(zs[row+1]+height/2)/height
            uv.extend([(j/columns,v0),((j+1)/columns,v0),((j+1)/columns,v1),(j/columns,v1)])
    return points,faces,uv


def floor_mesh(rng, centre, width, length, z=.002, yaw=0):
    polygon=outline(rng,width,length)
    c,s=math.cos(yaw),math.sin(yaw)
    points=[(centre[0],centre[1],z)]
    points += [(centre[0]+x*c-y*s,centre[1]+x*s+y*c,z) for x,y in polygon]
    faces=[]; uv=[]
    for i in range(len(polygon)):
        j=(i+1)%len(polygon)
        faces.append((0,i+1,j+1))
        uv.extend([(.5,.5),(polygon[i][0]/width+.5,polygon[i][1]/length+.5),
                   (polygon[j][0]/width+.5,polygon[j][1]/length+.5)])
    return points,faces,uv
