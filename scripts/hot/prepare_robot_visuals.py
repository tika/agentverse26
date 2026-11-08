"""Keep policy physics intact while expanding instanced render-only meshes."""
from pxr import Usd
root=stage.GetPrimAtPath('/World/WalkingSpot')
visuals=[str(p.GetPath()) for p in Usd.PrimRange(root)
         if p.IsInstance() and p.GetName()=='visuals']
for path in visuals:stage.GetPrimAtPath(path).SetInstanceable(False)
for _ in range(6):world.render()
state['expanded_robot_visuals']=sorted(set(state.get('expanded_robot_visuals',[]))|set(visuals))
print('[hot] expanded render-only robot instances '+str(len(visuals)),flush=True)
