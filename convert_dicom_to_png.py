#!/usr/bin/env python3
"""Convert DICOM files from input/ into patient-organized PNG folders."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
from PIL import Image
from pydicom.dataset import FileDataset
from pydicom.multival import MultiValue
from pydicom.pixel_data_handlers.util import apply_voi_lut


@dataclass(frozen=True)
class DicomImage:
    source: Path
    patient_id: str
    patient_name: str
    study_date: str
    study_time: str
    series_number: int
    instance_number: int
    acquisition_datetime: str
    acquisition_date: str
    acquisition_time: str
    content_date: str
    content_time: str
    image_position: str
    ds: FileDataset


def as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, MultiValue):
        return "_".join(as_text(item, default) for item in value)
    text = str(value).strip()
    return text if text else default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def slug(value: str, fallback: str = "unknown") -> str:
    value = value.replace("^", " ").strip()
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value)
    value = re.sub(r"\s+", "_", value)
    value = value.strip("._-")
    return value or fallback


def first_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, MultiValue) and value:
        value = value[0]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def dicom_sort_key(item: DicomImage) -> tuple:
    position_z = None
    try:
        position_z = float(as_text(item.ds.get("ImagePositionPatient", "")).split("\\")[-1])
    except ValueError:
        position_z = None

    return (
        item.acquisition_datetime,
        item.acquisition_date,
        item.acquisition_time,
        item.content_date,
        item.content_time,
        item.series_number,
        item.instance_number,
        position_z if position_z is not None else 0.0,
        item.source.name,
    )


def read_dicom_images(input_dir: Path) -> tuple[list[DicomImage], list[tuple[Path, str]]]:
    images: list[DicomImage] = []
    skipped: list[tuple[Path, str]] = []

    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(input_dir).parts):
            continue

        try:
            ds = pydicom.dcmread(path, force=True)
        except Exception as exc:
            skipped.append((path, f"not readable as DICOM: {exc}"))
            continue

        if "PixelData" not in ds:
            skipped.append((path, "no PixelData"))
            continue

        patient_id = slug(as_text(ds.get("PatientID"), "unknown_patient"))
        patient_name = slug(as_text(ds.get("PatientName"), patient_id))

        images.append(
            DicomImage(
                source=path,
                patient_id=patient_id,
                patient_name=patient_name,
                study_date=as_text(ds.get("StudyDate")),
                study_time=as_text(ds.get("StudyTime")),
                series_number=as_int(ds.get("SeriesNumber")),
                instance_number=as_int(ds.get("InstanceNumber")),
                acquisition_datetime=as_text(ds.get("AcquisitionDateTime")),
                acquisition_date=as_text(ds.get("AcquisitionDate")),
                acquisition_time=as_text(ds.get("AcquisitionTime")),
                content_date=as_text(ds.get("ContentDate")),
                content_time=as_text(ds.get("ContentTime")),
                image_position=as_text(ds.get("ImagePositionPatient")),
                ds=ds,
            )
        )

    return images, skipped


def normalize_grayscale(array: np.ndarray, ds: FileDataset) -> np.ndarray:
    arr = array.astype(np.float32)

    slope = first_number(ds.get("RescaleSlope"))
    intercept = first_number(ds.get("RescaleIntercept"))
    if slope is not None:
        arr *= slope
    if intercept is not None:
        arr += intercept

    try:
        arr = apply_voi_lut(arr, ds).astype(np.float32)
    except Exception:
        window_center = first_number(ds.get("WindowCenter"))
        window_width = first_number(ds.get("WindowWidth"))
        if window_center is not None and window_width and window_width > 0:
            low = window_center - window_width / 2
            high = window_center + window_width / 2
            arr = np.clip(arr, low, high)

    if as_text(ds.get("PhotometricInterpretation")).upper() == "MONOCHROME1":
        arr = arr.max() - arr

    arr_min = float(np.nanmin(arr))
    arr_max = float(np.nanmax(arr))
    if arr_max <= arr_min:
        return np.zeros(arr.shape, dtype=np.uint8)

    arr = (arr - arr_min) / (arr_max - arr_min)
    return (arr * 255).clip(0, 255).astype(np.uint8)


def pixel_array_to_images(ds: FileDataset) -> list[Image.Image]:
    array = ds.pixel_array

    if array.ndim == 2:
        return [Image.fromarray(normalize_grayscale(array, ds), mode="L")]

    if array.ndim == 3:
        samples_per_pixel = as_int(ds.get("SamplesPerPixel"), 1)
        if samples_per_pixel == 3 and array.shape[-1] == 3:
            arr = array
            if arr.dtype != np.uint8:
                arr = normalize_grayscale(arr, ds)
            return [Image.fromarray(arr.astype(np.uint8), mode="RGB")]
        return [Image.fromarray(normalize_grayscale(frame, ds), mode="L") for frame in array]

    if array.ndim == 4 and array.shape[-1] == 3:
        images: list[Image.Image] = []
        for frame in array:
            arr = frame
            if arr.dtype != np.uint8:
                arr = normalize_grayscale(arr, ds)
            images.append(Image.fromarray(arr.astype(np.uint8), mode="RGB"))
        return images

    raise ValueError(f"unsupported pixel array shape: {array.shape}")


def write_metadata_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def convert(input_dir: Path, output_dir: Path, max_files: int | None = None) -> None:
    images, skipped = read_dicom_images(input_dir)
    if max_files is not None:
        images = images[:max_files]
    by_patient: dict[str, list[DicomImage]] = {}
    failures: list[tuple[Path, str]] = []

    for item in images:
        by_patient.setdefault(item.patient_id, []).append(item)

    output_dir.mkdir(parents=True, exist_ok=True)

    for patient_id, patient_images in sorted(by_patient.items()):
        patient_images.sort(key=dicom_sort_key)
        patient_dir = output_dir / patient_id
        patient_dir.mkdir(parents=True, exist_ok=True)

        metadata_rows: list[dict[str, str]] = []
        output_index = 1

        for item in patient_images:
            try:
                frames = pixel_array_to_images(item.ds)
            except Exception as exc:
                failures.append((item.source, str(exc)))
                continue

            print(
                f"{patient_id}: {item.source.name} -> {len(frames)} frame(s)",
                flush=True,
            )
            for frame_number, image in enumerate(frames, start=1):
                suffix = f"_frame-{frame_number:03d}" if len(frames) > 1 else ""
                filename = f"{output_index:04d}_series-{item.series_number:03d}_instance-{item.instance_number:04d}{suffix}.png"
                destination = patient_dir / filename
                image.save(destination)

                metadata_rows.append(
                    {
                        "output_file": str(destination.relative_to(output_dir)),
                        "source_file": str(item.source),
                        "patient_id": item.patient_id,
                        "patient_name": item.patient_name,
                        "study_date": item.study_date,
                        "study_time": item.study_time,
                        "series_number": str(item.series_number),
                        "instance_number": str(item.instance_number),
                        "acquisition_datetime": item.acquisition_datetime,
                        "acquisition_date": item.acquisition_date,
                        "acquisition_time": item.acquisition_time,
                        "content_date": item.content_date,
                        "content_time": item.content_time,
                        "image_position_patient": item.image_position,
                        "frame_number": str(frame_number),
                    }
                )
                output_index += 1

        write_metadata_csv(patient_dir / "metadata.csv", metadata_rows)

    print(f"Converted PNG images for {len(by_patient)} patient(s) into: {output_dir}")
    print(f"Readable DICOM image files: {len(images)}")
    if skipped:
        print(f"Skipped non-image/non-DICOM files: {len(skipped)}")
        for path, reason in skipped[:10]:
            print(f"  skipped {path}: {reason}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more")
    if failures:
        print(f"Failed image conversions: {len(failures)}")
        for path, reason in failures[:10]:
            print(f"  failed {path}: {reason}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read DICOM metadata and export patient-organized PNG images."
    )
    parser.add_argument("--input", default="input", type=Path, help="Input directory with DICOM files.")
    parser.add_argument("--output", default="output", type=Path, help="Output directory for PNG files.")
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Convert only the first N readable DICOM image files. Useful for quick tests.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    convert(args.input, args.output, args.max_files)


if __name__ == "__main__":
    main()
