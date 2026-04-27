"""
모델 승격 도구
candidates/ → active/ (사용자 승인 후 실행)

흐름:
1. candidates/ 에서 최고 성능 모델 선택 (또는 지정)
2. 사용자 확인
3. active/vision_model.pt 로 복사
4. 이전 active 모델을 archive/ 로 이동
"""

import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ACTIVE_DIR = Path("models/active")
CANDIDATES_DIR = Path("models/candidates")
ARCHIVE_DIR = Path("models/archive")


def list_candidates() -> list:
    """candidates/ 폴더의 모델 목록 (성능순)"""
    candidates = []
    for pt_file in CANDIDATES_DIR.glob("*.pt"):
        eval_file = pt_file.with_suffix("").parent / (pt_file.stem + "_eval.json")
        acc = 0.0
        if eval_file.exists():
            with open(str(eval_file), encoding="utf-8") as f:
                data = json.load(f)
            acc = data.get("accuracy", 0.0)
        candidates.append({"file": pt_file, "accuracy": acc})

    candidates.sort(key=lambda c: c["accuracy"], reverse=True)
    return candidates


def promote(model_path: str = None, force: bool = False) -> bool:
    """
    모델 승격

    Args:
        model_path: 승격할 모델 경로 (None이면 최고 성능 자동 선택)
        force: 확인 프롬프트 없이 강제 실행

    Returns:
        성공 여부
    """
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # 후보 모델 결정
    if model_path:
        src = Path(model_path)
    else:
        candidates = list_candidates()
        if not candidates:
            logger.error("승격 가능한 후보 모델 없음")
            return False
        src = candidates[0]["file"]
        logger.info(f"최고 성능 후보 선택: {src.name} (acc={candidates[0]['accuracy']:.4f})")

    if not src.exists():
        logger.error(f"모델 파일 없음: {src}")
        return False

    # 사용자 확인 (interactive)
    if not force:
        print(f"\n승격할 모델: {src.name}")
        print("active/vision_model.pt 로 교체됩니다.")
        ans = input("계속하시겠습니까? (yes/no): ").strip().lower()
        if ans not in ("yes", "y"):
            print("취소됨")
            return False

    # 기존 active 모델 archive로 이동
    active_model = ACTIVE_DIR / "vision_model.pt"
    if active_model.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = ARCHIVE_DIR / f"vision_model_archived_{ts}.pt"
        shutil.move(str(active_model), str(archive_path))
        logger.info(f"기존 모델 보관: {archive_path.name}")

    # 새 모델 복사
    shutil.copy2(str(src), str(active_model))
    logger.info(f"모델 승격 완료: {src.name} → {active_model}")

    # meta 파일도 복사
    meta_src = src.with_suffix("").parent / (src.stem + "_meta.json")
    if meta_src.exists():
        shutil.copy2(str(meta_src), str(ACTIVE_DIR / "vision_model_meta.json"))

    # 승격 기록
    record = {
        "promoted_at": datetime.now().isoformat(),
        "source_file": src.name,
        "source_path": str(src),
    }
    with open(str(ACTIVE_DIR / "promote_history.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 모델 승격 완료: {src.name}")
    return True


if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).parent.parent)

    model_arg = None
    force = "--force" in sys.argv

    for arg in sys.argv[1:]:
        if arg.endswith(".pt"):
            model_arg = arg

    success = promote(model_path=model_arg, force=force)
    sys.exit(0 if success else 1)
