"""Register moving content and composite frames without repeated fixed chrome."""
import cv2
import numpy as np
from capture_tools import stitch_shift


def estimate_shift(previous,current):
    if previous.shape!=current.shape:return None
    h,w=previous.shape[:2]
    if min(h,w)<80:return None
    shift=stitch_shift(previous,current)
    scale=min(1.0,720/h,600/w)
    gray_a=cv2.cvtColor(previous,cv2.COLOR_BGR2GRAY)
    gray_b=cv2.cvtColor(current,cv2.COLOR_BGR2GRAY)
    if np.mean(cv2.absdiff(gray_a,gray_b))<.03:return 0
    a=cv2.resize(cv2.GaussianBlur(gray_a,(3,3),0),None,fx=scale,fy=scale)
    b=cv2.resize(cv2.GaussianBlur(gray_b,(3,3),0),None,fx=scale,fy=scale)
    small_h,small_w=a.shape
    candidates={}
    for row,fraction in enumerate((.06,.25,.44,.63)):
        y=int(small_h*fraction)
        th=max(12,int(small_h*.12))
        for column in range(3):
            x0=int(small_w*(column/3+.015))
            x1=int(small_w*((column+1)/3-.015))
            tile=b[y:y+th,x0:x1]
            if tile.size==0 or tile.std()<6:continue
            search=a[y:min(small_h,y+int(small_h*.75)+th),x0:x1]
            if search.shape[0]<tile.shape[0]:continue
            scores=cv2.matchTemplate(search,tile,cv2.TM_CCOEFF_NORMED).ravel()
            for value in np.argsort(scores)[-2:]:
                if value<1 or scores[value]<.82:continue
                distance=round(int(value)/scale)
                candidates.setdefault(distance,set()).add(row)
    accepted=[]
    distances=set()
    if shift is not None and shift>0:distances.add(shift)
    radius=int(np.ceil(1/scale))
    for distance,rows in candidates.items():
        if len(rows)>=2:distances.update(range(distance-radius,distance+radius+1))
    seed=shift if shift is not None and shift>0 else next(iter(distances),1)
    fixed=fixed_mask(previous,current,seed)
    for distance in distances:
        if distance<1 or distance>h*.75:continue
        difference=cv2.absdiff(gray_a[distance:],gray_b[:-distance])
        moving=~(fixed[distance:]|fixed[:-distance])
        if np.mean(moving)<.12:continue
        fraction=float(np.mean(difference[moving]<12))
        # A substantial majority must agree; a stationary toolbar alone cannot
        # establish motion. Repetitive/unrelated frames remain unaccepted.
        if fraction>.90:accepted.append((fraction,distance))
    if accepted:return max(accepted,key=lambda item:(item[0],-item[1]))[1]
    return 0 if shift==0 else None


def fixed_mask(previous,current,shift):
    h,w=current.shape[:2]
    a=cv2.cvtColor(previous,cv2.COLOR_BGR2GRAY)
    b=cv2.cvtColor(current,cv2.COLOR_BGR2GRAY)
    same=cv2.absdiff(a,b)<7
    mask=np.zeros((h,w),np.uint8)
    changed=np.mean(~same,axis=1)>.007
    moving_rows=np.flatnonzero(changed)
    if moving_rows.size:
        # Stationary edge bands (headers/footers) are retained at the outside
        # of the final image rather than copied into every newly exposed strip.
        top=min(int(moving_rows[0]),h//4)
        bottom=min(h-1-int(moving_rows[-1]),h//4)
        if top:mask[:top]=1
        if bottom:mask[-bottom:]=1
    edges=cv2.Canny(b,45,110)>0
    neighbourhood=cv2.boxFilter(same.astype(np.float32),-1,(3,3))
    seeds=(same & edges & (neighbourhood>.55)).astype(np.uint8)
    joined=cv2.morphologyEx(seeds,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    joined=cv2.dilate(joined,np.ones((3,3),np.uint8))
    _,_,edge_stats,_=cv2.connectedComponentsWithStats(joined)
    solid=cv2.morphologyEx(same.astype(np.uint8),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    _,_,solid_stats,_=cv2.connectedComponentsWithStats(solid)
    residual=np.zeros((h,w),bool)
    residual[:h-shift]=cv2.absdiff(a[shift:],b[:-shift])>12
    for stats in list(edge_stats[1:])+list(solid_stats[1:]):
        x,y,width,height,area=stats
        if width<10 or height<10 or area<20 or width*height>h*w*.35:continue
        box=np.s_[y:y+height,x:x+width]
        if np.mean(same[box])<.80:continue
        if y<h-shift and np.mean(residual[box])<.035:continue
        # A coherent unchanged edge with conflicting moving content is an
        # occlusion. Fill its bounding rectangle, including icon interiors.
        x0,y0=max(0,x-2),max(0,y-2)
        mask[y0:min(h,y+height+2),x0:min(w,x+width+2)]=1
    return mask.astype(bool)


class ContentStitcher:
    def __init__(self,frame,max_length=50000):
        self.previous=np.ascontiguousarray(frame).copy()
        self.canvas=self.previous.copy()
        self.valid=np.ones(frame.shape[:2],bool)
        self.last_written=np.ones(frame.shape[:2],bool)
        self.offset=0
        self.max_length=max_length
        self.count=1

    def append(self,frame):
        frame=np.ascontiguousarray(frame)
        shift=estimate_shift(self.previous,frame)
        if shift is None or shift==0:return shift
        h,w=frame.shape[:2]
        end=self.offset+shift+h
        if end>self.max_length:raise OverflowError('长截图长度已达上限')
        fixed=fixed_mask(self.previous,frame,shift)
        previous_valid=self.valid[self.offset:self.offset+h]
        # Invalidate only pixels actually supplied by the preceding frame.
        # An already recovered background must not be covered by a later icon.
        previous_valid[fixed & self.last_written]=False
        new_offset=self.offset+shift
        growth=end-self.canvas.shape[0]
        if growth:
            self.canvas=np.concatenate([self.canvas,frame[-growth:].copy()],axis=0)
            self.valid=np.concatenate([self.valid,np.zeros((growth,w),bool)],axis=0)
        target=self.canvas[new_offset:end]
        known=self.valid[new_offset:end]
        # If both observations are occluded, keep the latest coherent captured
        # overlay rather than combining half a former footer with half a button.
        fallback=fixed & (~known)
        target[fallback]=frame[fallback]
        # Prefer the latest unoccluded observation even in the overlap. This
        # also clears temporary redraw artifacts once clean pixels are seen.
        write=~fixed
        target[write]=frame[write]
        known[write]=True
        # Unknown occluded pixels keep a captured fallback, never fabricated
        # pixels. Later unoccluded observations replace that fallback naturally.
        self.last_written=write
        self.previous=frame.copy()
        self.offset=new_offset
        self.count+=1
        return shift

    def image(self):return self.canvas
