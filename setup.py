from setuptools import setup, find_namespace_packages

setup(
    name="muzero",
    version="1.0",
    author="Werner Duvaud et al",
    zip_safe=False,
    packages=find_namespace_packages(
        where='src',
        exclude=[]
    ),
    package_dir={'': 'src'},
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
