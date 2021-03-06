from setuptools import setup, find_packages
import hurr_durr
import os

setup_pth = os.path.dirname(__file__)
readme_pth = os.path.join(setup_pth, 'README.md')

setup(
    name='hurr-durr',
    version=hurr_durr.__version__,
    description='Streaming async interface to 4chan boards',
    author='Emils Solmanis',
    author_email='emils.solmanis@gmail.com',
    license='Apache License (2.0)',
    keywords='4chan stream async',
    url='https://github.com/emilssolmanis/hurr-durr',
    download_url='https://github.com/emilssolmanis/hurr-durr/archive/{version}.tar.gz'.format(
        version=hurr_durr.__version__
    ),
    long_description=open(readme_pth).read(),

    packages=find_packages(),
    scripts=['hurr-durr', 'hurr-durr-convert-file-to-sqlite'],
    zip_safe=True,

    install_requires=['tornado==4.0.2']
)
