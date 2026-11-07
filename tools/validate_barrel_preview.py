"""Reject missing yellow barrel surfaces in this specific appearance-study fixture."""
from pathlib import Path
import numpy as np
from PIL import Image


def validate(directory):
    directory=Path(directory)
    pixels=np.asarray(Image.open(directory/'normal_vs_bulged/rgb_0000.png').convert('RGB'),dtype=float)
    yellow=(pixels[:,:,0]>pixels[:,:,2]*1.25)&(pixels[:,:,1]>pixels[:,:,2]*1.2)&(pixels[:,:,0]>55)
    h,w=yellow.shape
    coverage=[]
    for left,right in ((.10,.30),(.40,.60),(.70,.90)):
        fraction=float(yellow[int(.28*h):int(.82*h),int(left*w):int(right*w)].mean())
        coverage.append(fraction)
    assert all(value>.25 for value in coverage),f'Missing barrel surfaces: yellow ROI fractions {coverage}'
    return {'fixture':'three yellow barrel study','all_three_paint_surfaces_present':True,
            'paint_roi_fractions':coverage}


if __name__=='__main__':
    import sys
    print(validate(sys.argv[1]))
