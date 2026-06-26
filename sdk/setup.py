"""Setup script for the Nexus AI SDK."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from setuptools import find_packages, setup

setup(
    name="nexus-ai-sdk",
    version="0.2.0",
    description="Python client library for Nexus AI API",
    long_description=open("README.md").read() if Path("README.md").exists() else "",
    long_description_content_type="text/markdown",
    author="Nexus Systems",
    python_requires=">=3.10",
    packages=find_packages(where=".", include=["*"]),
    package_dir={"": "."},
    install_requires=[],
    extras_require={
        "async": ["httpx>=0.25.0", "anyio>=3.7.0"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)