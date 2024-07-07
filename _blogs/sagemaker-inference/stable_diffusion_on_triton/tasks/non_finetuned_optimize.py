import os
import shutil
import subprocess
import tarfile

import flytekit
import torch
from diffusers import DiffusionPipeline
from flytekit import Resources, task
from flytekit.extras.accelerators import A10G
from flytekit.types.directory import FlyteDirectory
from flytekit.types.file import FlyteFile

from .optimize import sd_compilation_image


@task(
    cache=True,
    cache_version="2.8",
    container_image=sd_compilation_image,
    requests=Resources(gpu="1", mem="20Gi"),
    accelerator=A10G,
)
def optimize_model_non_finetuned(model: str) -> FlyteDirectory:
    model_repository = flytekit.current_context().working_directory
    vae_dir = os.path.join(model_repository, "vae")
    encoder_dir = os.path.join(model_repository, "text_encoder")
    pipeline_dir = os.path.join(model_repository, "pipeline")

    os.makedirs(vae_dir, exist_ok=True)
    os.makedirs(encoder_dir, exist_ok=True)
    os.makedirs(pipeline_dir, exist_ok=True)

    vae_1_dir = os.path.join(vae_dir, "1")
    encoder_1_dir = os.path.join(encoder_dir, "1")

    os.makedirs(vae_1_dir, exist_ok=True)
    os.makedirs(encoder_1_dir, exist_ok=True)

    vae_plan = os.path.join(vae_1_dir, "model.plan")
    encoder_onnx = os.path.join(encoder_1_dir, "model.onnx")

    result = subprocess.run(
        f"/root/export.sh {vae_plan} {encoder_onnx} {model}",
        capture_output=True,
        text=True,
        shell=True,
    )

    # Check the return code
    if result.returncode == 0:
        print("Script execution succeeded")
        print(f"stdout: {result.stdout}")
    else:
        print("Script execution failed")
        print(f"stderr: {result.stderr}")

    shutil.copy("/root/vae_config.pbtxt", os.path.join(vae_dir, "config.pbtxt"))
    shutil.copy(
        "/root/text_encoder_config.pbtxt",
        os.path.join(encoder_dir, "config.pbtxt"),
    )

    pipeline = DiffusionPipeline.from_pretrained(
        model,
        torch_dtype=torch.float16,
    ).to("cuda")
    pipeline.save_pretrained("model")
    shutil.copytree(
        "model", os.path.join(pipeline_dir, "fused-lora"), dirs_exist_ok=True
    )

    shutil.copytree("/root/pipeline", pipeline_dir, dirs_exist_ok=True)

    return FlyteDirectory(model_repository)


@task(cache=True, cache_version="2", requests=Resources(mem="5Gi"))
def compress_model_non_finetuned(model_repo: FlyteDirectory) -> FlyteFile:
    model_file_name = "stable-diff-bls.tar.gz"

    with tarfile.open(model_file_name, mode="w:gz") as tar:
        tar.add(model_repo.download(), arcname=".")

    return FlyteFile(model_file_name)
