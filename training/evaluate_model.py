"""
Vision 모델 평가
models/candidates/ → test 데이터셋으로 정확도/혼동행렬 평가
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader
    from torchvision import datasets, transforms
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

IMAGE_SIZE = 224
NUM_CLASSES = 3


def get_test_transform():
    return transforms.Compose([
        transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])


def load_model(model_path: str):
    if not TORCH_AVAILABLE:
        return None, None

    checkpoint = torch.load(model_path, map_location="cpu")
    model_name = checkpoint.get("model_name", "resnet18")

    from torchvision import models
    if model_name == "resnet18":
        model = models.resnet18(weights=None)
        model.fc = nn.Linear(model.fc.in_features, NUM_CLASSES)
    elif model_name == "efficientnet_b0":
        model = models.efficientnet_b0(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, NUM_CLASSES)
    else:
        raise ValueError(f"알 수 없는 모델: {model_name}")

    model.load_state_dict(checkpoint["model_state_dict"])
    return model, checkpoint


def evaluate_model(
    model_path: str,
    test_dir: str = "datasets/chart_images/test",
    batch_size: int = 32,
) -> Optional[dict]:
    """모델 평가 및 리포트 반환"""
    if not TORCH_AVAILABLE:
        logger.error("PyTorch 미설치")
        return None

    test_path = Path(test_dir)
    if not test_path.exists():
        logger.error(f"테스트 데이터 없음: {test_dir}")
        return None

    model, checkpoint = load_model(model_path)
    if model is None:
        return None

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    model.eval()

    test_ds = datasets.ImageFolder(str(test_path), transform=get_test_transform())
    if len(test_ds) == 0:
        logger.warning("테스트 이미지 없음")
        return {"accuracy": 0.0, "samples": 0}

    loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    class_names = test_ds.classes
    conf_matrix = [[0] * len(class_names) for _ in range(len(class_names))]
    correct, total = 0, 0

    with torch.no_grad():
        for imgs, labels in loader:
            imgs, labels = imgs.to(device), labels.to(device)
            outputs = model(imgs)
            preds = outputs.argmax(dim=1)
            for p, t in zip(preds.cpu().tolist(), labels.cpu().tolist()):
                conf_matrix[t][p] += 1
            correct += (preds == labels).sum().item()
            total += imgs.size(0)

    accuracy = correct / max(total, 1)

    # Per-class precision/recall
    per_class = {}
    for i, cls in enumerate(class_names):
        tp = conf_matrix[i][i]
        fn = sum(conf_matrix[i]) - tp
        fp = sum(row[i] for row in conf_matrix) - tp
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        per_class[cls] = {"precision": round(precision, 4), "recall": round(recall, 4), "count": sum(conf_matrix[i])}

    report = {
        "model_path": model_path,
        "accuracy": round(accuracy, 4),
        "samples": total,
        "class_names": class_names,
        "per_class": per_class,
        "confusion_matrix": conf_matrix,
        "training_val_acc": checkpoint.get("best_val_acc", 0.0),
        "created_at": checkpoint.get("created_at", ""),
    }

    logger.info(f"평가 완료: accuracy={accuracy:.4f} samples={total}")
    for cls, m in per_class.items():
        logger.info(f"  {cls}: precision={m['precision']:.4f} recall={m['recall']:.4f} count={m['count']}")

    return report


def evaluate_all_candidates(
    candidates_dir: str = "models/candidates",
    test_dir: str = "datasets/chart_images/test",
) -> list:
    """candidates/ 폴더의 모든 모델 평가"""
    candidates_path = Path(candidates_dir)
    model_files = sorted(candidates_path.glob("*.pt"))

    results = []
    for mf in model_files:
        logger.info(f"\n평가 중: {mf.name}")
        report = evaluate_model(str(mf), test_dir)
        if report:
            report["model_file"] = mf.name
            results.append(report)

            report_path = mf.with_suffix("_eval.json")
            with open(str(report_path), "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

    results.sort(key=lambda r: r.get("accuracy", 0), reverse=True)
    if results:
        logger.info(f"\n최고 성능 모델: {results[0]['model_file']} (acc={results[0]['accuracy']:.4f})")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.chdir(Path(__file__).parent.parent)
    results = evaluate_all_candidates()
    if results:
        print(f"\n평가 결과 (상위 3개):")
        for r in results[:3]:
            print(f"  {r['model_file']}: acc={r['accuracy']:.4f}")
    else:
        print("평가 가능한 모델 없음")
