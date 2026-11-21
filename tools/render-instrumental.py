"""Render original ACE-independent arrangement JSON to aligned stems, mix and multitrack MIDI.
Requirements: Python 3 + numpy, libfluidsynth, ffmpeg + an existing GM SoundFont.
Usage: python render03.py --soundfont /path/to/GM.sf2 --out OUTPUT score.json ...
"""
import argparse, ctypes as C, json, math, pathlib, struct, subprocess, tempfile, zipfile
import numpy as np

SR=32000
P=C.c_void_p; I=C.c_int; S=C.c_char_p
lib=None
def bind(n,res,*args):
 f=getattr(lib,n); f.restype=res;f.argtypes=args;return f
def init(libpath):
 global lib,newset,num,setint,new,load,prog,on,off,cc,write,delete,dset
 lib=C.CDLL(libpath)
 newset=bind('new_fluid_settings',P)
 num=bind('fluid_settings_setnum',I,P,S,C.c_double)
 setint=bind('fluid_settings_setint',I,P,S,I)
 new=bind('new_fluid_synth',P,P); load=bind('fluid_synth_sfload',I,P,S,I)
 prog=bind('fluid_synth_program_change',I,P,I,I); on=bind('fluid_synth_noteon',I,P,I,I,I)
 off=bind('fluid_synth_noteoff',I,P,I,I); cc=bind('fluid_synth_cc',I,P,I,I,I)
 write=bind('fluid_synth_write_float',I,P,I,P,I,I,P,I,I)
 delete=bind('delete_fluid_synth',None,P); dset=bind('delete_fluid_settings',None,P)
def vl(n):
 b=[n&127];n>>=7
 while n:b.insert(0,128|(n&127));n>>=7
 return bytes(b)
def meta(kind,content):return bytes([255,kind])+vl(len(content))+content
def wavcmd(path, data, fmt):
 enc={'flac':['-c:a','flac','-compression_level','5'],'mp3':['-c:a','libmp3lame','-b:a','96k']}[fmt]
 subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','s16le','-ar',str(SR),'-ac','2','-i','-',
                 *enc,str(path)],input=data.tobytes(),check=True)
def suffix(n):return struct.pack('>I',len(n))+n
def midfile(tracks,anchors,meter,bpm,end,path):
 metaevents=[]
 def tr(events):
  t=0;b=bytearray()
  for at,data in sorted(events,key=lambda z:z[0]):
   k=round(at*480);b+=vl(k-t)+data;t=k
  b+=vl(max(0,round(end*480)-t))+meta(47,b'')
  return b'MTrk'+suffix(b)
 metaevents.extend([(0,meta(81,round(60000000/bpm).to_bytes(3,'big'))),
                    (0,meta(88,bytes([6,3,36,8] if meter==3 else [4,2,24,8])))])
 metaevents.extend((t,meta(6,n.encode())) for t,n in anchors)
 ts=[tr(metaevents)]
 for ch,(name,patch,pan,events) in tracks.items():
  if not events:continue
  x=[(0,meta(3,name.encode())),(0,bytes([0xb0+ch,10,pan]))]
  if ch!=9:x.append((0,bytes([0xc0+ch,patch])))
  x.extend((t,bytes([(0x90 if on else 0x80)+ch,k,v])) for t,on,k,v in sorted(events))
  ts.append(tr(x))
 path.write_bytes(b'MThd'+struct.pack('>IHHH',6,1,len(ts),480)+b''.join(ts))
names={
 'ballad':['lead-flute','piano','cello','violin'],
 'soul':['lead-tenor-sax','electric-piano','electric-bass','clean-guitar'],
 'waltz':['lead-A-clarinet','nylon-guitar','upright-bass','accordion'],
 'rock':['lead-synth','distorted-guitar','electric-bass','overdriven-guitar'],
 'road':['lead-clarinet','plucked-lute','electric-bass','cello'],
 'folk':['lead-clarinet','steel-guitar','upright-bass','piano'],
}
def arrangement(s):
 m=s['meter']; groove=s['groove']; tracks={j:[name,patch,[64,46,64,80][j],[]] for j,(name,patch) in enumerate(zip(names[groove],[s['lead'],*s['patches']]))}
 if groove=='waltz':tracks[4]=['lead-B-flute',73,74,[]]
 tracks[9]=['drums',0,64,[]]
 def n(ch,t,d,k,v):
  if d<=0 or not 0<k<128:raise ValueError((ch,t,d,k))
  e=tracks[ch][3];v=max(1,min(127,round(v)));e.extend([(t,1,k,v),(t+d,0,k,0)])
 i=0; anchors=[]; compact=[]
 for sec in s['sections']:
  name=sec['name']; low=name.lower(); anchors.append((i*m,name))
  den=float(sec.get('density',.7));assert 0<=den<=1
  hook=('chor' in low or '副歌' in name or '尾钩' in name)
  sparse=sec.get('sparse',False) or (groove=='rock' and '桥段' in name)
  compact.append([name,len(sec['bars']),den])
  for j,b in enumerate(sec['bars']):
   t=i*m; q=t; pitches=b['chord'];root=min(pitches); assert 3<=len(pitches)<=5
   while root>52:root-=12
   while root<36:root+=12
   last= j==len(sec['bars'])-1;last_song=last and sec is s['sections'][-1]
   role=b.get('lead_role',sec.get('lead_role','A'))
   played=0
   for k,d in b['notes']:
    if k:
     ch=4 if groove=='waltz' and role=='B' else 0
     v=72+23*den+2*(played%3==0)
     n(ch,q,d*(.96 if groove in ('ballad','folk','waltz') else .87),k,v)
     if groove=='waltz' and role=='both':n(4,q,d*.91,k, v-19)
     played+=1
    q+=d
   assert abs(q-t-m)<.00001,(s['title'],name,i,q-t)
   if sparse:
    if groove!='rock':
     n(3,t,m*.9,pitches[min(1,len(pitches)-1)]-12,46+20*den)
     if j%2==0:n(1,t+m*.25,m*.46,pitches[0],39+20*den)
    else:n(3,t,m*.88,pitches[(j+1)%len(pitches)]-12,39+20*den)
   elif last_song:
    for k in pitches:n(1,t,m*.84,k-(12 if groove in ('rock','road') else 0),43+29*den)
    n(2,t,m*.8,root,42+25*den)
   elif groove in ('ballad','folk','waltz','road'):
    step=.5 if m==3 or groove=='road' else (0.5 if den>.78 else 1)
    for z in range(round(m/step)):
     if den<.36 and z%2:continue
     at=z*step
     ix=((z if j%2==0 else z*2+1)+i//4)%len(pitches)
     n(1,t+at,min(m-at,step*(1.3 if groove!='road' else .77)),pitches[ix],34+22*den+7*(z%3==0))
    if groove=='ballad':
     if den>.3:
      for k in pitches[1:3]:n(2,t,m*.9,k-12,32+26*den)
    elif den>.27:
     for z in ([0,m/2] if den>.55 else [0]):n(2,t+z,m*.41,root+(7 if z and j%2 else 0),44+25*den)
   elif groove in ('soul','rock'):
    hits=[.5,2.5] if groove=='soul' and den>.55 else ([0,2.5] if groove=='soul' else ([0,.75,1.5,2,2.75,3.5] if hook else [0,1.5,2.5,3.5]))
    for z in hits:
     if den<.39 and z>2:continue
     pitches_to_play=pitches if groove=='soul' else [pitches[0]-12,pitches[0]-5,pitches[0]]
     for k in pitches_to_play:n(1,t+z,min(m-z,.9 if groove=='soul' else .5),k,43+28*den)
    if den>.27:
     for z in ([0,1.5,2.5,3.5] if den>.52 else [0,2.5]):
      n(2,t+z,min(m-z,.58),root+(7 if z==2.5 and j%2 else 0)-(12 if groove=='rock' else 0),49+34*den)
   if not sparse and not last_song and (hook or (den>.55 and j%4==3)):
    if groove=='rock':
     if j%2==1:
      for k in pitches[-2:]:n(3,t+2,m*.43,k,48+23*den)
    else:
     octv=12 if groove=='ballad' else (0 if groove!='road' else -12)
     if groove=='ballad':
      for k in pitches[-2:]:n(3,t+1.5,2.35,k+octv,29+26*den)
     elif j%2==1:
      for z,k in enumerate(pitches[-2:]):n(3,t+z*m/2,m*.4,k+octv,30+25*den)
   if not sparse and not last_song and groove in ('soul','road','rock','waltz') and den>(.23 if groove=='rock' else .42):
    if groove=='waltz':
     for z,k,v in [(0,36,55),(1.5,38,48),(2.5,42,43)]:n(9,t+z,.09,k,v*den)
    else:
     strength=den*(1 if groove=='rock' else .77)
     for z in ([0,2.5,3.5] if groove=='rock' and hook else [0,2.5]):n(9,t+z,.11,36,54+42*strength)
     for z in [1,3]:n(9,t+z,.11,38,42+43*strength)
     for z in range(8 if groove=='rock' else 4):
      n(9,t+z*(.5 if groove=='rock' else 1),.07,42,27+34*strength+(11 if z%2==0 else 0))
     if last and hook and den>.7:n(9,t+3.5,.4,49,55+35*strength)
   i+=1
 return tracks,anchors,i*m,compact
def rendersolo(events,channel,patch,pan,sf,end,samples_per_beat):
 st=newset();num(st,b'synth.sample-rate',SR);num(st,b'synth.gain',.65)
 setint(st,b'synth.cpu-cores',1);sy=new(st)
 try:
  if load(sy,str(sf).encode(),1)<0:raise RuntimeError('failed to load SoundFont')
  if channel!=9:prog(sy,channel,patch)
  cc(sy,channel,10,pan)
  audio=np.empty((end,2),dtype=np.float32);pos=0
  def render(stop):
   nonlocal pos
   if stop>pos:
    start=audio[pos:];assert write(sy,stop-pos,start.ctypes.data,0,2,start.ctypes.data,1,2)==0
    pos=stop
  for t,active,k,v in sorted(events):
   render(round(t*samples_per_beat));(on(sy,channel,k,v) if active else off(sy,channel,k))
  render(end)
  length=SR//5;audio[-length:]*=np.linspace(1,0,length)[:,None]
  return audio
 finally:delete(sy);dset(st)
def decode(p):
 return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-f','s16le','-']),dtype='<i2')
def main(s,out,sf):
 out.mkdir(parents=True,exist_ok=True)
 bpm=s['bpm']; meter=s['meter'];tracks,anchors,beats,sec=arrangement(s)
 if len(sec)<6:raise ValueError('not a full arrangement')
 spb=SR*60/bpm;duration=beats*60/bpm+2.3;assert 145<=duration<=220
 end=round(duration*SR)
 midfile(tracks,anchors,meter,bpm,beats,out/'arrangement.mid')
 rms={};meta=[]
 with tempfile.TemporaryDirectory(dir=out) as temp:
  temp=pathlib.Path(temp);mixf=np.zeros((end,2),dtype=np.float32)
  for c,(name,patch,pan,events) in tracks.items():
   if not events:continue
   a=rendersolo(events,c,patch,pan,sf,end,spb);mixf+=a
   peak=float(np.max(np.abs(a)));rms[name]=float(np.sqrt(np.mean(a*a)))
   if peak<.0005:raise ValueError('silent '+name)
   p=temp/(name+'.npy');np.save(p,a)
   meta.append((name,p,len(events)//2))
  gain=.84/float(max(.001,np.max(np.abs(mixf)))); del mixf
  sum_pcm=np.zeros((end,2),dtype=np.int32)
  with zipfile.ZipFile(out/'stems-flac.zip','w',compression=zipfile.ZIP_STORED) as z:
   z.writestr('README.txt','Stereo, 32000 Hz, 16-bit lossless FLAC. All stems begin at 00:00 and end on the same sample. Sum at unity gain with pan centered in a 32000 Hz session. Do not normalize tracks independently. Convert to WAV with ffmpeg -i stem.flac stem.wav if needed. Song: '+s['title']+'\n')
   for name,p,_ in meta:
    pcm=np.rint(np.load(p)*gain*32767).astype('<i2'); flac=p.with_suffix('.flac')
    wavcmd(flac,pcm,'flac')
    plain=decode(flac);assert len(plain)==end*2 and np.array_equal(plain,pcm.reshape(-1)),name
    sum_pcm+=pcm
    z.write(flac,name+'.flac')
  assert np.max(np.abs(sum_pcm))<32767
  master=sum_pcm.astype('<i2')
  wavcmd(out/'mix-lossless.flac',master,'flac')
  assert np.array_equal(decode(out/'mix-lossless.flac'),master.reshape(-1))
  wavcmd(out/'mix.mp3',master,'mp3')
  approx=decode(out/'mix.mp3');assert abs(len(approx)-end*2)<SR*2
  result={'slug':s['slug'],'duration':round(duration,2),'tracks':[{'name':n,'notes':e,'rms_before_master_gain':round(rms[n],5)} for n,p,e in meta],
          'bar_count':round(beats/meter),'sections':sec,'sample_rate':SR,'frames_per_track':end,'channels':2,
          'peak_dBFS':round(20*math.log10(float(np.max(np.abs(sum_pcm)))/32768),1),'lossless_sum_pcm_exact':True}
  (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--soundfont',type=pathlib.Path,required=True)
 ap.add_argument('--fluid-library',default='libfluidsynth.so.3');ap.add_argument('--out',type=pathlib.Path,required=True)
 ap.add_argument('scores',nargs='+',type=pathlib.Path)
 a=ap.parse_args();init(a.fluid_library)
 for path in a.scores:
  s=json.loads(path.read_text());main(s,a.out/s['slug'],a.soundfont)
