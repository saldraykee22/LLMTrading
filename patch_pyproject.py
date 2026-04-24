with open("pyproject.toml", "r") as f:
    content = f.read()

content += """
[tool.setuptools.packages.find]
exclude = ["tests*", "logs*", "data*", "docs*"]
"""

with open("pyproject.toml", "w") as f:
    f.write(content)
