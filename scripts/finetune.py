"""Doladění MegaDescriptoru na vašich hulmanech (ArcFace).

Bere výřezy, které už jsou v galerii aplikace (data/hulmany.db), takže stačí
hulmany nejdřív nafotit/natočit přes aplikaci nebo scripts/import_folders.py.

    python scripts/finetune.py                 # výchozí nastavení pro RTX 3060
    python scripts/finetune.py --epochs 30 --batch 8

Na konci uloží models/finetuned-<model>.pth. Aplikace ho použije po restartu
nebo po kliknutí na „Načíst doladěný model“ v sekci Stav.
"""
import argparse
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.transforms as T
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, media  # noqa: E402
from app.config import settings  # noqa: E402
from app.device import resolve_device  # noqa: E402
from app.embedder import MODELS, build_transform, create_backbone, finetuned_path, resolve_model_name  # noqa: E402


class ArcFace(nn.Module):
    def __init__(self, dim: int, classes: int, scale: float = 64.0, margin: float = 0.5):
        super().__init__()
        self.weight = nn.Parameter(torch.randn(classes, dim) * 0.01)
        self.scale, self.margin = scale, margin

    def forward(self, emb, labels):
        cos = F.linear(F.normalize(emb), F.normalize(self.weight)).clamp(-1 + 1e-7, 1 - 1e-7)
        theta = torch.acos(cos)
        target = torch.cos(theta + self.margin)
        onehot = F.one_hot(labels, cos.size(1)).bool()
        logits = torch.where(onehot, target, cos) * self.scale
        return F.cross_entropy(logits, labels)


class Crops(torch.utils.data.Dataset):
    def __init__(self, items, transform):
        self.items, self.transform = items, transform

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        path, label = self.items[i]
        return self.transform(Image.open(path).convert("RGB")), label


def load_samples(kinds):
    rows = db.query("SELECT individual_id, kind, crop_path, source FROM samples")
    rows = [r for r in rows if r["kind"] in kinds and media.media_path(r["crop_path"]).exists()]
    return rows


def split_by_source(rows, val_fraction, seed):
    """Validace z jiných souborů/videí než trénink, jinak by přesnost vyšla falešně vysoká."""
    rng = random.Random(seed)
    sources = defaultdict(set)
    for r in rows:
        sources[r["individual_id"]].add(r["source"])
    val_sources = set()
    for ind, src in sources.items():
        src = sorted(src)
        rng.shuffle(src)
        n_val = int(len(src) * val_fraction)
        if len(src) >= 2:
            n_val = max(1, n_val)
        val_sources |= {(ind, s) for s in src[:n_val]}
    train = [r for r in rows if (r["individual_id"], r["source"]) not in val_sources]
    val = [r for r in rows if (r["individual_id"], r["source"]) in val_sources]
    return train, val


@torch.inference_mode()
def embed_all(model, items, transform, device, batch):
    loader = torch.utils.data.DataLoader(Crops(items, transform), batch_size=batch, num_workers=0)
    feats, labels = [], []
    model.eval()
    for x, y in loader:
        with torch.autocast("cuda", dtype=torch.float16, enabled=device == "cuda"):
            f = model(x.to(device))
        feats.append(F.normalize(f.float(), dim=1).cpu())
        labels.append(y)
    return torch.cat(feats), torch.cat(labels)


def knn_top1(model, train_items, val_items, transform, device, batch):
    if not val_items:
        return None
    g, gl = embed_all(model, train_items, transform, device, batch)
    q, ql = embed_all(model, val_items, transform, device, batch)
    pred = gl[(q @ g.T).argmax(dim=1)]
    return (pred == ql).float().mean().item()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=None, choices=list(MODELS), help="výchozí: podle nastavení aplikace")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--lr", type=float, default=2e-5, help="učící krok páteře (hlava ArcFace má 100×)")
    p.add_argument("--val", type=float, default=0.2, help="podíl souborů na validaci")
    p.add_argument("--kinds", default="face,body")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--timm-arch", default=None, help=argparse.SUPPRESS)  # jen pro testy bez internetu
    args = p.parse_args()

    torch.manual_seed(args.seed)
    device = resolve_device()
    model_name = args.model or resolve_model_name()
    size = MODELS[model_name][1]
    rows = load_samples(set(args.kinds.split(",")))
    individuals = sorted({r["individual_id"] for r in rows})
    if len(individuals) < 2:
        sys.exit("Potřebuji aspoň 2 hulmany s fotkami v galerii.")
    label_of = {ind: i for i, ind in enumerate(individuals)}
    train_rows, val_rows = split_by_source(rows, args.val, args.seed)
    to_items = lambda rs: [(str(media.media_path(r["crop_path"])), label_of[r["individual_id"]]) for r in rs]  # noqa: E731
    train_items, val_items = to_items(train_rows), to_items(val_rows)
    print(f"Model {model_name} na {device}; {len(individuals)} hulmanů, "
          f"{len(train_items)} tréninkových a {len(val_items)} validačních výřezů.")

    if args.timm_arch:
        import timm
        model = timm.create_model(args.timm_arch, num_classes=0, pretrained=False, img_size=size)
    else:
        model = create_backbone(model_name, pretrained=True)
    out_path = finetuned_path(model_name)
    model.to(device)
    if device == "cuda" and hasattr(model, "set_grad_checkpointing"):
        model.set_grad_checkpointing(True)  # aby se L-384 vešel do 12 GB
    dim = model.num_features
    head = ArcFace(dim, len(individuals)).to(device)

    train_tf = T.Compose([
        T.RandomResizedCrop(size, scale=(0.6, 1.0), ratio=(0.8, 1.25)),
        T.RandomApply([T.ColorJitter(0.3, 0.3, 0.2, 0.02)], p=0.8),
        T.RandomRotation(10),
        T.ToTensor(),
        T.Normalize([0.5] * 3, [0.5] * 3),
    ])
    eval_tf = build_transform(size)
    loader = torch.utils.data.DataLoader(Crops(train_items, train_tf), batch_size=args.batch, shuffle=True,
                                         num_workers=args.workers, drop_last=len(train_items) > args.batch)
    opt = torch.optim.AdamW([
        {"params": model.parameters(), "lr": args.lr},
        {"params": head.parameters(), "lr": args.lr * 100},
    ], weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs * max(1, len(loader)))
    scaler = torch.amp.GradScaler("cuda", enabled=device == "cuda")

    base = knn_top1(model, train_items, val_items, eval_tf, device, args.batch)
    if base is not None:
        print(f"Přesnost před doladěním (top-1 na validaci): {base:.1%}")
    best = -1.0 if base is None else base
    saved = False
    for epoch in range(1, args.epochs + 1):
        model.train()
        head.train()
        t0, total, n = time.time(), 0.0, 0
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            with torch.autocast("cuda", dtype=torch.float16, enabled=device == "cuda"):
                emb = model(x)
            loss = head(emb.float(), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += loss.item() * len(y)
            n += len(y)
        acc = knn_top1(model, train_items, val_items, eval_tf, device, args.batch)
        msg = f"Epocha {epoch}/{args.epochs}: ztráta {total / max(1, n):.3f}"
        if acc is not None:
            msg += f", přesnost {acc:.1%}"
        print(f"{msg} ({time.time() - t0:.0f} s)")
        if acc is None or acc >= best:
            best = acc if acc is not None else best
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = out_path.with_suffix(".tmp")
            torch.save({"backbone": model.state_dict(), "model": model_name,
                        "individuals": individuals, "val_top1": acc}, tmp)
            tmp.replace(out_path)
            saved = True
    if saved:
        print(f"Hotovo. Nejlepší model uložen do {out_path}. Restartujte aplikaci nebo v ní klikněte "
              f"na „Načíst doladěný model“.")
    else:
        print("Doladění nepřekonalo původní model, nic jsem neukládal. Zkuste víc fotek nebo jiné --lr.")


if __name__ == "__main__":
    main()
