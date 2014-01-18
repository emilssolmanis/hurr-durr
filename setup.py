from setuptools import setup, find_packages


setup(
    name='hurr-durr',
    version = '0.0.1',
    description='Streaming async interface to 4chan boards',
    author='Emils Solmanis',
    author_email='emils.solmanis@gmail.com',
    license='Apache License (2.0)',
    keywords='4chan stream async',
    url='https://github.com/emilssolmanis/hurr-durr',

    packages=find_packages(),
    scripts=['hurr-durr'],
    zip_safe=True,

    install_requires=['tornado==3.2']
)
