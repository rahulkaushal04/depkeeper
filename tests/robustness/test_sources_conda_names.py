"""Table tests for which conda dependency names are skipped as conda-only."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from depkeeper.core.sources.conda_yaml import CondaYamlAdapter, _is_non_pypi

CONDA_ONLY = [
    # base / system libraries
    "pip", "openssl", "ca-certificates", "zlib", "xz", "tk", "sqlite", "readline",
    "ncurses", "libffi", "libgomp", "libxml2", "libgcc-ng", "libstdcxx-ng",
    "libgfortran5", "libgfortran-ng", "libblas", "liblapack", "_libgcc_mutex",
    "_openmp_mutex", "python_abi", "ld_impl_linux-64", "libzlib", "bzip2",
    # data science
    "mkl", "mkl-include", "intel-openmp", "blas", "r-base", "r-ggplot2",
    # CUDA / pytorch
    "cudatoolkit", "cudnn", "nccl", "pytorch-cuda", "cuda-nvcc", "cuda-runtime",
    "cuda-version", "cuda-cudart-dev", "cuda-toolkit", "cudatoolkit-dev",
    "Libgcc-NG",
]  # fmt: skip

PYPI = [
    # the regression: prefixes that look conda-ish but are PyPI projects
    "cuda-python", "cuda-bindings", "cuda-core", "libvirt-python", "mkl-service",
    "mkl_fft", "mkl_random", "libgpuarray", "librosa", "libsass", "libclang",
    "libcst", "libtmux", "pyopenssl", "nvidia-cudnn-cu12",
    # data science / bioinformatics / ML
    "numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "jupyterlab",
    "biopython", "pysam", "scikit-bio", "torch", "torchvision", "tensorflow",
    "samtools", "bedtools", "setuptools", "wheel", "tzdata", "cmake", "certifi",
    "requests",
]  # fmt: skip


@pytest.mark.parametrize("name", CONDA_ONLY)
def test_conda_only_names_are_skipped(name: str) -> None:
    assert _is_non_pypi(name)


@pytest.mark.parametrize("name", PYPI)
def test_pypi_names_are_kept(name: str) -> None:
    assert not _is_non_pypi(name)


ENVS = {
    "data-science": (
        "name: ds\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.11\n"
        "  - numpy=1.26\n  - pandas>=2.0\n  - mkl=2023.1\n  - libgcc-ng\n"
        "  - openssl=3.0\n  - mkl-service=2.4\n  - pip\n",
        ["numpy", "pandas", "mkl-service"],
    ),
    "cuda-pytorch": (
        "dependencies:\n  - python=3.10\n  - pytorch=2.1\n  - cudatoolkit=11.8\n"
        "  - pytorch-cuda=11.8\n  - cuda-python=12.0\n  - cuda-nvcc\n  - cudnn\n"
        "  - nccl\n  - torchvision\n",
        ["torch", "cuda-python", "torchvision"],
    ),
    "bioinformatics": (
        "channels:\n  - bioconda\ndependencies:\n  - biopython=1.81\n"
        "  - bioconda::samtools=1.17\n  - libzlib\n  - ncurses\n  - r-base=4.3\n"
        "  - libvirt-python\n  - pysam\n",
        ["biopython", "samtools", "libvirt-python", "pysam"],
    ),
}


@pytest.mark.parametrize("env", sorted(ENVS))
def test_real_environment_examples(env: str, tmp_path: Path) -> None:
    text, expected = ENVS[env]
    p = tmp_path / "environment.yml"
    p.write_text(text)
    names: List[str] = [r.name for r in CondaYamlAdapter().parse(p)]
    assert sorted(names) == sorted(expected)
