from setuptools import setup, find_packages


setup(
    name='databucket-python-client',
    version='1.0.0',
    license='MIT',
    author="Krzysztof Słysz",
    author_email='kslysz@gmail.com',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    url='https://github.com/databucket/databucket-python-client',
    keywords='databucket',
    install_requires=[
          'scikit-learn',
      ],

)
