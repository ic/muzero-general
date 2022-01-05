from setuptools import setup

setup(
    name="muzero",
    version="1.0",
    author="Werner Duvaud et al",
    zip_safe=False,
    install_requires=[
        "gym",
        "hiredis",
        "nevergrad",
        "numpy",
        "ray",
        "seaborn",
        "tensorboard",
        "torch==1.7.1",
    ]
)
