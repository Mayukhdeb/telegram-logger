import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="telegram_logger",
    version="0.0.0",
    description="watch your scripts go brr on telegram",
    author="a very bored mayukh on a sunday night",
    author_email="",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/mayukhdeb/telegram-logger",
    packages=setuptools.find_packages(),
    install_requires=None,
    classifiers=[
        "Operating System :: OS Independent",
    ],
)