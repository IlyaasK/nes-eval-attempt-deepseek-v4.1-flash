import subprocess, os, numpy as np, sys
env=dict(os.environ); env.update({k:v for k,v in (a.split('=') for a in sys.argv[1:])})
def measure():
    tot=0; frames=0
    for g in ('rhde','robotfindskitten','stallar','file-fixers'):
        R='.oracle-out/vid_%s/ref'%g
        md='/tmp/me_%s'%g
        subprocess.run(['rm','-rf',md]); os.makedirs(md,exist_ok=True)
        subprocess.run(['/task/tools/nesrun_trace','/task/dev-roms/%s.nes'%g,'400','--out',md],capture_output=True,env=env)
        for f in sorted(os.listdir(R)):
            if not f.endswith('.idx'): continue
            a=np.fromfile(os.path.join(R,f),dtype='<u2'); b=np.fromfile(os.path.join(md,f),dtype='<u2')
            if a.shape!=b.shape: continue
            n=int((a!=b).sum())
            if n: tot+=n; frames+=1
    return tot, frames
print('%s -> %d px in %d frames' % (sys.argv[1:] or 'default', *measure()))
