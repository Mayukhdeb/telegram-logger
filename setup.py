import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

"""
release checklist:
0. cleanup `rm -rf tgtqdm.egg-info build dist/`
1. update version on `setup.py`
4. commit changes and push
5. make release on PyPI. Run the following commands:
    5.1 `python3 setup.py sdist bdist_wheel`
    5.2 (optional) `python3 -m pip install --user --upgrade twine`
    5.3 `python3 -m twine upload dist/*`
6. git tag the release: `git tag vX.Y.Z` and `git push origin vX.Y.Z`
"""

setuptools.setup(
    name="tgtqdm",
    version="0.2.0",
    description="watch your scripts go brr on telegram",
    author="a very bored mayukh on a sunday night",
    author_email="",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/mayukhdeb/tgtqdm",
    packages=setuptools.find_packages(include=["tgtqdm", "tgtqdm.*"]),
    python_requires=">=3.8",
    install_requires=["requests>=2.20"],
    extras_require={"dev": ["pytest>=7", "mypy>=1.0", "types-requests"]},
    package_data={"tgtqdm": ["py.typed"]},
    classifiers=[
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
    ],
)