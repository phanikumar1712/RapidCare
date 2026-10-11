ls"""
Dataset utilities: class discovery, corrupt-image filtering, stratified splits
and tf.data pipelines.

Class names are discovered dynamically from the folder structure under
data/raw/  —  nothing is hard-coded. Expected layout:

    data/raw/
        ClassNameA/*.jpg
        ClassNameB/*.png
        ...
"""

import logging
from pathlib import Path

import numpy as np
import tensorflow as tf
from PIL import Image, UnidentifiedImageError
from sklearn.model_selection import train_test_split

from ml.utils import BATCH_SIZE, DATA_DIR, IMG_SIZE, SEED

logger = logging.getLogger(__name__)

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


# --------------------------------------------------------------- discovery ----


def discover_classes(data_dir: Path = DATA_DIR) -> list:
    """Return sorted class names = names of sub-directories containing images."""
    data_dir = Path(data_dir)
    if not data_dir.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {data_dir}\n"
            "Download the Kaggle wound dataset and place class folders there "
            "(see data/README.md), then run scripts/check_dataset.py."
        )
    classes = sorted(
        d.name
        for d in data_dir.iterdir()
        if d.is_dir() and any(f.suffix.lower() in VALID_EXTENSIONS for f in d.iterdir() if f.is_file())
    )
    if len(classes) < 2:
        raise ValueError(
            f"Expected >= 2 class folders with images under {data_dir}, found {len(classes)}: {classes}"
        )
    return classes


def scan_dataset(data_dir: Path = DATA_DIR) -> tuple:
    """
    Walk the dataset and return (file_paths, labels, class_names, skipped_count).

    Corrupt / unreadable images are detected with PIL and skipped so a few bad
    files cannot crash a training run.
    """
    class_names = discover_classes(data_dir)
    name_to_idx = {name: i for i, name in enumerate(class_names)}

    paths, labels, skipped = [], [], 0
    for class_dir in sorted((Path(data_dir) / c for c in class_names), key=lambda p: p.name):
        idx = name_to_idx[class_dir.name]
        for f in sorted(class_dir.iterdir()):
            if not (f.is_file() and f.suffix.lower() in VALID_EXTENSIONS):
                continue
            try:
                with Image.open(f) as img:  # validates the file can be opened
                    img.verify()
                paths.append(str(f))
                labels.append(idx)
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                logger.warning("Skipping corrupt image %s (%s)", f.name, exc)
                skipped += 1

    return paths, labels, class_names, skipped


# ------------------------------------------------------------------ splits ----


def stratified_split(paths, labels, val_fraction=0.15, test_fraction=0.15):
    """
    Stratified train/val/test split preserving class proportions.

    Returns (train_paths, train_labels, val_paths, val_labels,
             test_paths, test_labels).
    """
    train_paths, hold_paths, train_labels, hold_labels = train_test_split(
        paths,
        labels,
        test_size=val_fraction + test_fraction,
        stratify=labels,
        random_state=42,
    )
    hold_is_test = test_fraction / (val_fraction + test_fraction)
    val_paths, test_paths, val_labels, test_labels = train_test_split(
        hold_paths,
        hold_labels,
        test_size=hold_is_test,
        stratify=hold_labels,
        random_state=42,
    )
    return train_paths, train_labels, val_paths, val_labels, test_paths, test_labels


# ------------------------------------------------------------- oversampling ----


def oversample_to_balance(paths, labels, seed: int = SEED):
    """
    Repeat minority-class samples (with replacement) until every class has as
    many training samples as the largest class.

    Applies to the TRAIN split only — val/test must stay natural, otherwise
    evaluation numbers would be invented. The result is shuffled so epochs do
    not start with large blocks of a single class.

    Returns (paths, labels) with integer labels.
    """
    rng = np.random.default_rng(seed)
    labels_arr = np.asarray(labels, dtype=np.int64)
    counts = np.bincount(labels_arr)
    max_count = int(counts.max())

    all_paths = list(paths)
    new_paths, new_labels = [], []
    for idx, count in enumerate(counts):
        cls_paths = [p for p, l in zip(all_paths, labels_arr) if l == idx]
        new_paths.extend(cls_paths)
        new_labels.extend([int(idx)] * len(cls_paths))
        need = max_count - len(cls_paths)
        if need > 0:
            extra = rng.choice(cls_paths, size=need, replace=True).tolist()
            new_paths.extend(extra)
            new_labels.extend([int(idx)] * need)

    order = rng.permutation(len(new_paths))
    return [new_paths[i] for i in order], [new_labels[i] for i in order]


# --------------------------------------------------------------- pipelines ----


def _load_image(path, label):
    """Read a file, decode, force 3 channels, resize to IMG_SIZE. Values 0-255."""
    img = tf.io.read_file(path)
    img = tf.image.decode_image(img, channels=3, expand_animations=False)
    img.set_shape([None, None, 3])  # decode_image loses static shape info
    img = tf.image.resize(img, IMG_SIZE)
    return img, label


def make_dataset(paths, labels, class_names, training=False):
    """
    Build a tf.data pipeline that yields batches of (image_0_255, one_hot_label).

    NOTE on preprocessing: pixel values are kept in [0, 255]. MobileNetV2's
    [-1, 1] rescaling is applied INSIDE the model (a Rescaling layer) so the
    exact same preprocessing runs at train and inference time with no skew.
    Augmentation lives inside the model too and is active only when the model
    is in training mode.
    """
    ds = tf.data.Dataset.from_tensor_slices((list(paths), list(labels)))
    if training:
        ds = ds.shuffle(buffer_size=min(len(paths), 2048), reshuffle_each_iteration=True)
    ds = ds.map(_load_image, num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.batch(BATCH_SIZE)
    ds = ds.map(lambda x, y: (x, tf.one_hot(y, depth=len(class_names))),
                num_parallel_calls=tf.data.AUTOTUNE)
    return ds.prefetch(tf.data.AUTOTUNE)
