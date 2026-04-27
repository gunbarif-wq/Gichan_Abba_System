"""
Vision 모델 학습
PyTorch ResNet18 / EfficientNet
datasets/chart_images/{train,val,test}/{Success,Fail,Sideways}
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader
    from torchvision import datasets, models, transforms
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch 미설치 - pip install torch torchvision")


LABEL_MAP = {"Fail": 0, "Sideways": 1, "Success": 2}
NUM_CLASSES = 3
BATCH_SIZE = 32
EPOCHS = 20
LEARNING_RATE = 1e-4
IMAGE_SIZE = 224


def get_transforms(is_train: bool):
    if is_train:
        return transforms.Compose([
            transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
            transforms.RandomHorizontalFlip(p=0.3),
            transforms.ColorJitter(brightness=0.1, contrast=0.1),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
    else:
        return transforms.Compose([
            transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])


def build_model(model_name: str = "resnet18", pretrained: bool = True) -> "nn.Module":
    if model_name == "resnet18":
        if pretrained:
            model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
        else:
            model = models.resnet18(weights=None)
        model.fc = nn.Linear(model.fc.in_features, NUM_CLASSES)
    elif model_name == "efficientnet_b0":
        if pretrained:
            model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
        else:
            model = models.efficientnet_b0(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, NUM_CLASSES)
    else:
        raise ValueError(f"지원하지 않는 모델: {model_name}")
    return model


def train_epoch(model, loader, optimizer, criterion, device) -> tuple:
    model.train()
    total_loss, correct, total = 0.0, 0, 0
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        optimizer.zero_grad()
        outputs = model(imgs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * imgs.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += imgs.size(0)
    return total_loss / max(total, 1), correct / max(total, 1)


def eval_epoch(model, loader, criterion, device) -> tuple:
    model.eval()
    total_loss, correct, total = 0.0, 0, 0
    with torch.no_grad():
        for imgs, labels in loader:
            imgs, labels = imgs.to(device), labels.to(device)
            outputs = model(imgs)
            loss = criterion(outputs, labels)
            total_loss += loss.item() * imgs.size(0)
            preds = outputs.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += imgs.size(0)
    return total_loss / max(total, 1), correct / max(total, 1)


def train_vision_model(
    data_dir: str = "datasets/chart_images",
    output_dir: str = "models/candidates",
    model_name: str = "resnet18",
    epochs: int = EPOCHS,
    batch_size: int = BATCH_SIZE,
    lr: float = LEARNING_RATE,
) -> Optional[str]:
    """
    Vision 모델 학습
    Returns: 저장된 모델 경로 또는 None
    """
    if not TORCH_AVAILABLE:
        logger.error("PyTorch 미설치")
        return None

    data_path = Path(data_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    train_dir = data_path / "train"
    val_dir = data_path / "val"

    if not train_dir.exists():
        logger.error(f"학습 데이터 없음: {train_dir}")
        return None

    # 데이터셋
    train_ds = datasets.ImageFolder(str(train_dir), transform=get_transforms(True))
    val_ds = datasets.ImageFolder(str(val_dir), transform=get_transforms(False))

    if len(train_ds) == 0:
        logger.error("학습 이미지 없음")
        return None

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    logger.info(f"학습 이미지: {len(train_ds)}, 검증 이미지: {len(val_ds)}")
    logger.info(f"클래스 매핑: {train_ds.class_to_idx}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Device: {device}")

    model = build_model(model_name).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.5)

    best_val_acc = 0.0
    best_epoch = 0
    history = []

    for epoch in range(1, epochs + 1):
        t0 = time.time()
        tr_loss, tr_acc = train_epoch(model, train_loader, optimizer, criterion, device)
        va_loss, va_acc = eval_epoch(model, val_loader, criterion, device)
        scheduler.step()

        elapsed = time.time() - t0
        logger.info(
            f"Epoch {epoch:02d}/{epochs} "
            f"tr_loss={tr_loss:.4f} tr_acc={tr_acc:.3f} "
            f"va_loss={va_loss:.4f} va_acc={va_acc:.3f} ({elapsed:.1f}s)"
        )
        history.append({"epoch": epoch, "tr_loss": tr_loss, "tr_acc": tr_acc, "va_loss": va_loss, "va_acc": va_acc})

        if va_acc > best_val_acc:
            best_val_acc = va_acc
            best_epoch = epoch

    # 저장
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_filename = f"vision_{model_name}_{ts}_acc{best_val_acc:.3f}.pt"
    model_path = str(output_path / model_filename)

    torch.save({
        "model_state_dict": model.state_dict(),
        "model_name": model_name,
        "num_classes": NUM_CLASSES,
        "class_to_idx": train_ds.class_to_idx,
        "best_val_acc": best_val_acc,
        "best_epoch": best_epoch,
        "epochs": epochs,
        "history": history,
        "created_at": ts,
    }, model_path)

    meta_path = model_path.replace(".pt", "_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "model_name": model_name,
            "model_file": model_filename,
            "best_val_acc": best_val_acc,
            "best_epoch": best_epoch,
            "train_samples": len(train_ds),
            "val_samples": len(val_ds),
            "class_to_idx": train_ds.class_to_idx,
            "created_at": ts,
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"모델 저장: {model_path}")
    logger.info(f"최고 검증 정확도: {best_val_acc:.3f} (epoch {best_epoch})")
    return model_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.chdir(Path(__file__).parent.parent)
    result = train_vision_model()
    if result:
        print(f"\n학습 완료: {result}")
    else:
        print("\n학습 실패 - 로그 확인")
