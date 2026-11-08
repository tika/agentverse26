"""CPU-only, known-map navigation and evidence ledger for the full-store mission.

Only inventory geometry is used here. Authored defect states and source strengths
are not planner inputs. A completed inspection is independent of its condition.
"""
import hashlib
import heapq
import json
import math

AISLES = {'A': 2.0, 'B': 6.0, 'C': 6.0, 'D': 10.0}


class StoreRouter:
    def __init__(self, drums, resolution=.1, robot_radius=.56):
        self.drums = drums
        self.resolution = resolution
        self.margin = robot_radius + .03
        self.nx, self.ny = round(20 / resolution), round(12 / resolution)
        self.exclusions = []
        self._free = {}

    def free(self, p):
        x, y = p[:2]
        if not self.margin <= x <= 20-self.margin or not self.margin <= y <= 12-self.margin:
            return False
        if any(math.hypot(x-d['x'], y-d['y']) < d['radius']+self.margin for d in self.drums):
            return False
        return not any(math.dist((x,y), z['centre']) < z['radius']+self.margin for z in self.exclusions)

    def line_free(self, a, b):
        n = max(1, math.ceil(math.dist(a[:2], b[:2])/.04))
        return all(self.free((a[0]+(b[0]-a[0])*i/n, a[1]+(b[1]-a[1])*i/n)) for i in range(n+1))

    def cell(self, p):
        return round(p[0]/self.resolution), round(p[1]/self.resolution)

    def point(self, cell):
        return cell[0]*self.resolution, cell[1]*self.resolution

    def route(self, start, goal):
        start, goal = tuple(start[:2]), tuple(goal[:2])
        if not self.free(start) or not self.free(goal):
            return None
        if self.line_free(start, goal):
            return [goal]
        first, last = self.cell(start), self.cell(goal)
        queue = [(0., first)]
        costs, parents = {first: 0.}, {}
        while queue:
            _, node = heapq.heappop(queue)
            if node == last:
                cells = [node]
                while node != first:
                    node = parents[node]
                    cells.append(node)
                raw = [start]+[self.point(c) for c in reversed(cells)]+[goal]
                result, i = [], 0
                while i < len(raw)-1:
                    j = len(raw)-1
                    while j > i+1 and not self.line_free(raw[i],raw[j]):
                        j -= 1
                    result.append(raw[j]); i = j
                return result
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt = node[0]+dx,node[1]+dy
                if nxt not in self._free:
                    self._free[nxt] = self.free(self.point(nxt))
                if not self._free[nxt]:
                    continue
                if dx and dy and not (self.free(self.point((node[0]+dx,node[1]))) and
                                      self.free(self.point((node[0],node[1]+dy)))):
                    continue
                cost = costs[node]+math.hypot(dx,dy)*self.resolution
                if cost >= costs.get(nxt,float('inf')):
                    continue
                costs[nxt],parents[nxt] = cost,node
                priority = cost+math.dist(self.point(nxt),goal)
                heapq.heappush(queue,(priority,nxt))
        return None

    def viewpoints(self, drum):
        y = AISLES[drum['row']]
        return [(drum['x']+dx,y) for dx in (-.3,.3,.65)]

    @staticmethod
    def length(start, path):
        return sum(math.dist(a,b) for a,b in zip([tuple(start[:2])]+path,path))


class CoverageLedger:
    def __init__(self, drums):
        self.geometry={d['id']:d for d in drums}
        self.drums = {d['id']:dict(views=[],attempts=0,deferred=None,complete=False,missing=['id','thermal','two_visual_angles'])
                      for d in drums}
        geometry = [{k:d[k] for k in ('id','display_id','x','y','radius','row')} for d in drums]
        self.map_sha256 = hashlib.sha256(json.dumps(geometry,sort_keys=True).encode()).hexdigest()

    def visual(self, drum_id, position, *, range_m, area, confidence, time_s):
        if not (.2 < range_m <= 3.8 and area >= 1500 and confidence >= .25):
            return False
        entry = self.drums[drum_id]
        drum=self.geometry[drum_id]
        bearing=math.atan2(position[1]-drum['y'],position[0]-drum['x'])
        if any(math.dist(position[:2],v['position_m']) < .35 or
               abs((bearing-v['bearing_rad']+math.pi)%(2*math.pi)-math.pi)<math.radians(12) for v in entry['views']):
            return False
        entry['views'].append(dict(position_m=list(map(float,position[:2])),range_m=round(range_m,2),
                                   bearing_rad=bearing,area_px=round(area),confidence=round(confidence,3),time_s=round(time_s,2)))
        return True

    def sync(self, memory):
        for drum_id, entry in self.drums.items():
            m = memory[drum_id]; checks = m['checks']; ident = checks.get('id',{})
            resolved = ident.get('result')=='match' or (ident.get('result')=='mismatch' and ident.get('confirmed'))
            thermal = checks.get('thermal',{})
            missing = ([] if resolved else ['id']) + ([] if math.isfinite(thermal.get('surface_c',float('nan'))) else ['thermal'])
            if len(entry['views']) < 2 or 'visual' not in checks:
                missing.append('two_visual_angles')
            entry['missing'] = missing
            entry['complete'] = not missing and not entry['deferred']
            m.update(complete=entry['complete'],missing=missing,
                     inspection_state='deferred' if entry['deferred'] else 'complete' if entry['complete'] else
                     'inspecting' if checks else 'pending',valid_viewpoints=len(entry['views']),deferred_reason=entry['deferred'])

    def counts(self):
        return dict(total=len(self.drums),complete=sum(d['complete'] for d in self.drums.values()),
                    deferred=sum(bool(d['deferred']) for d in self.drums.values()),
                    pending=sum(not d['complete'] and not d['deferred'] for d in self.drums.values()))

    def snapshot(self):
        return dict(schema_version=1,map_sha256=self.map_sha256,counts=self.counts(),drums=self.drums)

    def restore(self, snapshot):
        if snapshot['map_sha256'] != self.map_sha256 or set(snapshot['drums']) != set(self.drums):
            raise ValueError('Checkpoint belongs to a different warehouse inventory')
        self.drums = snapshot['drums']
