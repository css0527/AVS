from pathlib import Path
import os
os.environ['MPLCONFIGDIR']='/tmp/avs_mpl'
import xml.etree.ElementTree as ET
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

root=Path(__file__).resolve().parent.parent
def transform(text):
 p=list(map(float,(text or '0 0 0 0 0 0').split()));x,y,z,a,b,c=p
 rx=np.array([[1,0,0],[0,np.cos(a),-np.sin(a)],[0,np.sin(a),np.cos(a)]])
 ry=np.array([[np.cos(b),0,np.sin(b)],[0,1,0],[-np.sin(b),0,np.cos(b)]])
 rz=np.array([[np.cos(c),-np.sin(c),0],[np.sin(c),np.cos(c),0],[0,0,1]])
 t=np.eye(4);t[:3,:3]=rz@ry@rx;t[:3,3]=[x,y,z];return t
fig=plt.figure(figsize=(10,7),facecolor='#1D2C42');ax=fig.add_subplot(111,projection='3d',facecolor='#1D2C42')
all_faces=[];all_colors=[]
for link in ET.parse(root/'avs_ws/src/avs_rescue_sim/models/rescue_rover/model.sdf').findall('.//model/link'):
 for visual in link.findall('visual'):
  t=transform(link.findtext('pose'))@transform(visual.findtext('pose'));g=visual.find('geometry');faces=[]
  color=list(map(float,visual.findtext('material/diffuse').split()))[:3]
  if g.find('box') is not None:
   dims=np.array(list(map(float,g.findtext('box/size').split())))/2
   pts=np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]])*dims
   faces=[pts[f] for f in [[0,1,2,3],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]]
  elif g.find('cylinder') is not None:
   radius=float(g.findtext('cylinder/radius'));h=float(g.findtext('cylinder/length'))/2;a=np.linspace(0,2*np.pi,49)
   bot=np.c_[radius*np.cos(a),radius*np.sin(a),np.full(len(a),-h)];top=bot.copy();top[:,2]=h
   faces=[bot[:-1],top[:-1]]+[np.array([bot[i],bot[i+1],top[i+1],top[i]]) for i in range(len(a)-1)]
  else:
   radius=float(g.findtext('sphere/radius'));a=np.linspace(0,2*np.pi,24);b=np.linspace(0,np.pi,12)
   pts=np.array([[[radius*np.cos(u)*np.sin(v),radius*np.sin(u)*np.sin(v),radius*np.cos(v)] for u in a] for v in b])
   faces=[np.array([pts[j,i],pts[j,i+1],pts[j+1,i+1],pts[j+1,i]]) for j in range(11) for i in range(23)]
  faces=[f@t[:3,:3].T+t[:3,3] for f in faces]
  colors=[]
  for f in faces:
   normal=np.cross(f[1]-f[0],f[2]-f[0]);normal/=max(np.linalg.norm(normal),1e-9)
   shade=.62+.38*abs(np.dot(normal,np.array([.3,-.4,.85])))
   colors.append(np.clip(np.array(color)*shade,0,1))
  all_faces.extend(faces);all_colors.extend(colors)
ax.add_collection3d(Poly3DCollection(all_faces,facecolors=all_colors,edgecolors=(0,0,0,.12),linewidths=.3))
ax.set_xlim(-.25,.39);ax.set_ylim(-.2,.2);ax.set_zlim(0,.34);ax.set_box_aspect((.64,.4,.34));ax.view_init(elev=35,azim=-48);ax.set_axis_off()
fig.subplots_adjust(0,0,1,1)
fig.savefig(root/'创新点PPT/素材/整车结构展示.png',dpi=220,facecolor=fig.get_facecolor(),bbox_inches='tight',pad_inches=.02)

from PIL import Image, ImageChops
p=root/'创新点PPT/素材/整车结构展示.png'
im=Image.open(p).convert('RGB');b=Image.new('RGB',im.size,im.getpixel((0,0)));bounds=ImageChops.difference(im,b).getbbox();im.crop((max(0,bounds[0]-60),max(0,bounds[1]-60),min(im.width,bounds[2]+60),min(im.height,bounds[3]+60))).save(p)
