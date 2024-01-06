import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="plaid-sync",
    version="0.0.1",
    author="Matthew Bafford",
    author_email="matthew@bafford.us",
    description="Command-line interface to the Plaid API that synchronizes your bank/credit card transactions with a local SQLite database. Written in Python 3.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/henryrobbins/onm.git",
    packages=setuptools.find_packages(),
    include_package_data=True,
    package_data={'plaid-sync': ['html/*', 'config/*']},
    license="MIT License",
    classifiers=[],
    entry_points={
        'console_scripts': [
            'plaid-sync = plaidsync.main:main',
        ],
    },
    install_requires=[
        "plaid-python==7.1.0"
    ],
    python_requires='>=3.7'
)
