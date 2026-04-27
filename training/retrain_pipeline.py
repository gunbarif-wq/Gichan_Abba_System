"""
재학습 파이프라인
CSV → 3분봉 → 라벨링 → 이미지 생성 → 학습 → 평가
한 번에 실행되는 전체 파이프라인
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def run_pipeline(
    csv_dir: str = "data/csv",
    model_name: str = "resnet18",
    epochs: int = 20,
    skip_image_gen: bool = False,
) -> dict:
    """
    전체 재학습 파이프라인 실행

    Args:
        csv_dir: 1분봉 CSV 폴더
        model_name: 'resnet18' 또는 'efficientnet_b0'
        epochs: 학습 에폭
        skip_image_gen: 이미 이미지가 있으면 True로 건너뜀

    Returns:
        파이프라인 결과 dict
    """
    result = {
        "started_at": datetime.now().isoformat(),
        "steps": {},
        "success": False,
    }

    logger.info("=" * 60)
    logger.info("Gichan Abba - Vision 재학습 파이프라인 시작")
    logger.info("=" * 60)

    # Step 1: CSV → 3분봉
    logger.info("\n[Step 1] CSV → 3분봉 변환")
    try:
        from training.csv_to_candles import convert_all_csvs
        converted = convert_all_csvs(csv_dir=csv_dir)
        result["steps"]["csv_to_candles"] = {"symbols": len(converted), "ok": True}
        logger.info(f"  완료: {len(converted)}개 종목")
    except Exception as e:
        logger.error(f"  실패: {e}")
        result["steps"]["csv_to_candles"] = {"ok": False, "error": str(e)}
        return result

    # Step 2: 라벨링
    logger.info("\n[Step 2] 라벨 생성")
    try:
        from training.label_tool import build_labels_csv
        labels_df = build_labels_csv()
        label_dist = dict(labels_df["label"].value_counts()) if len(labels_df) else {}
        result["steps"]["labeling"] = {"total": len(labels_df), "distribution": label_dist, "ok": True}
        logger.info(f"  완료: {len(labels_df)}개 라벨 - {label_dist}")
    except Exception as e:
        logger.error(f"  실패: {e}")
        result["steps"]["labeling"] = {"ok": False, "error": str(e)}
        return result

    # Step 3: 이미지 생성
    if not skip_image_gen:
        logger.info("\n[Step 3] 차트 이미지 생성")
        try:
            from training.make_chart_images import build_all_images
            img_counts = build_all_images()
            result["steps"]["image_gen"] = {"counts": img_counts, "ok": True}
            logger.info(f"  완료: {img_counts}")
        except Exception as e:
            logger.error(f"  실패: {e}")
            result["steps"]["image_gen"] = {"ok": False, "error": str(e)}
    else:
        logger.info("\n[Step 3] 이미지 생성 건너뜀 (skip_image_gen=True)")
        result["steps"]["image_gen"] = {"skipped": True, "ok": True}

    # Step 4: 모델 학습
    logger.info("\n[Step 4] Vision 모델 학습")
    try:
        from training.train_vision_model import train_vision_model
        model_path = train_vision_model(model_name=model_name, epochs=epochs)
        if model_path:
            result["steps"]["training"] = {"model_path": model_path, "ok": True}
            logger.info(f"  완료: {model_path}")
        else:
            result["steps"]["training"] = {"ok": False, "error": "학습 실패"}
            return result
    except Exception as e:
        logger.error(f"  실패: {e}")
        result["steps"]["training"] = {"ok": False, "error": str(e)}
        return result

    # Step 5: 평가
    logger.info("\n[Step 5] 모델 평가")
    try:
        from training.evaluate_model import evaluate_model
        eval_report = evaluate_model(model_path)
        if eval_report:
            result["steps"]["evaluation"] = {
                "accuracy": eval_report.get("accuracy", 0),
                "samples": eval_report.get("samples", 0),
                "ok": True,
            }
            logger.info(f"  완료: accuracy={eval_report.get('accuracy', 0):.4f}")
    except Exception as e:
        logger.warning(f"  평가 실패 (학습은 성공): {e}")
        result["steps"]["evaluation"] = {"ok": False, "error": str(e)}

    result["success"] = True
    result["finished_at"] = datetime.now().isoformat()
    logger.info("\n" + "=" * 60)
    logger.info("파이프라인 완료!")
    logger.info("=" * 60)
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )
    os.chdir(Path(__file__).parent.parent)

    skip_img = "--skip-images" in sys.argv
    result = run_pipeline(skip_image_gen=skip_img)

    print(f"\n{'✅ 성공' if result['success'] else '❌ 실패'}")
    for step, info in result["steps"].items():
        status = "✅" if info.get("ok") else "❌"
        print(f"  {status} {step}: {info}")
