import os
from setuptools import setup, find_packages

setup(
    name="red-shinobi",
    version="1.0.0",
    author="Brojen Gurung",
    author_email="",
    description="RED SHINOBI - Multi-Agent AI Terminal with MCP Support",
    long_description=open("README.md").read() if os.path.exists("README.md") else "RED SHINOBI Multi-Agent AI Terminal",
    long_description_content_type="text/markdown",
    url="https://github.com/BrozG/red-shinobi",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "": ["ascii-art.txt"],
    },
    install_requires=[
        "openai>=1.14.0",
        "anthropic>=0.20.0",
        "requests>=2.31.0",
        "python-dotenv>=1.0.1",
        "rich>=13.7.1",
        "textual>=0.52.1",
        "prompt_toolkit>=3.0.43",
        "aiohttp>=3.9.0",
    ],
    entry_points={
        "console_scripts": [
            "red=red_shinobi.main:main",
        ],
    },
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
