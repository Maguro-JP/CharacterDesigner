import os,sys,time
os.environ.setdefault("HF_HOME","/home/user/CharacterDesigner/.cache/gen/hf"); os.environ["HF_HUB_OFFLINE"]="1"
import torch
from diffusers import StableDiffusionXLPipeline, EulerAncestralDiscreteScheduler
torch.set_num_threads(os.cpu_count())
p=StableDiffusionXLPipeline.from_pretrained("cagliostrolab/animagine-xl-4.0",torch_dtype=torch.bfloat16)
p.scheduler=EulerAncestralDiscreteScheduler.from_config(p.scheduler.config)
pr="1girl, solo, beautiful girl, portrait, head and shoulders, three-quarter view, face turned to the left, looking to the side, long flowing hair, detailed beautiful eyes, gentle smile, delicate features, simple white background, masterpiece, high score, great score, absurdres"
ng="lowres, bad anatomy, bad hands, text, watermark, signature, frame, border, extra eyes, deformed face, blurry, worst quality, low quality, hands"
for s in map(int,sys.argv[1:]):
    t=time.time()
    im=p(pr,negative_prompt=ng,width=832,height=832,num_inference_steps=24,guidance_scale=5,generator=torch.Generator().manual_seed(s)).images[0]
    im.save(f"girl-s{s}.png"); print("done",s,round(time.time()-t),flush=True)
