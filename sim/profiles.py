"""64-segment revolved drum profiles, with continuous body UVs and smooth normals."""
import math


def drum_profile(category):
    if category == 'LLW':
        h, body = .88, .278
        profile = [(.270,0),(.285,0),(.290,.005),(.290,.017),(.282,.026),(body,.035)]
        for z in (h/3,2*h/3):
            profile += [(body,z-.018),(.283,z-.012),(.288,z-.004),
                        (.288,z+.004),(.283,z+.012),(body,z+.018)]
        return profile + [(body,h-.038),(.283,h-.024),(.289,h-.014),
                          (.290,h-.006),(.285,h),(.274,h),(.269,h-.008),(.269,h-.015)]
    if category == 'ILW':
        return [(.375,0),(.392,0),(.396,.007),(.396,.018),(.390,.028),
                (.390,1.152),(.391,1.162),(.393,1.167),(.393,1.173),
                (.391,1.178),(.390,1.181),(.400,1.186),(.400,1.196),
                (.395,1.200),(.365,1.200),(.360,1.190),(.360,1.155)]
    raise ValueError('Category must be LLW or ILW')


def radius_at(profile, z):
    radii = []
    for (r0,z0),(r1,z1) in zip(profile,profile[1:]):
        if min(z0,z1) <= z <= max(z0,z1):
            radii.append(max(r0,r1) if z0==z1 else r0+(r1-r0)*(z-z0)/(z1-z0))
    return max(radii) if radii else profile[0][0]


def make_drum_mesh(profile, bulge=None, dents=None):
    if bulge is not None or dents:
        raise NotImplementedError('Shape faults belong to Step 5; Step 2 creates nominal drums.')
    segments, height = 64, max(z for _,z in profile)
    points, vertex_normals = [], []
    for i,(radius,z) in enumerate(profile):
        previous, following = profile[max(0,i-1)],profile[min(len(profile)-1,i+1)]
        dr, dz = following[0]-previous[0],following[1]-previous[1]
        length = math.hypot(dr,dz) or 1
        for j in range(segments):
            angle = j*2*math.pi/segments
            c,s = math.cos(angle),math.sin(angle)
            points.append((radius*c,radius*s,z))
            vertex_normals.append((dz/length*c,dz/length*s,-dr/length))
    faces,uv,normals = [],[],[]
    for i in range(len(profile)-1):
        for j in range(segments):
            k = (j+1)%segments
            face = (i*segments+j,i*segments+k,(i+1)*segments+k,(i+1)*segments+j)
            faces.append(face)
            uv.extend([(j/segments,profile[i][1]/height),((j+1)/segments,profile[i][1]/height),
                       ((j+1)/segments,profile[i+1][1]/height),(j/segments,profile[i+1][1]/height)])
            normals.extend(vertex_normals[index] for index in face)
    bottom = list(reversed(range(segments)))
    faces.append(bottom)
    radius = profile[0][0]
    uv.extend((.5+points[index][0]/(2*radius),.5+points[index][1]/(2*radius)) for index in bottom)
    normals.extend([(0,0,-1)]*segments)
    return {'points':points,'faces':faces,'uv':uv,'normals':normals}
