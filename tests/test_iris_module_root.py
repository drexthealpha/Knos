"""The IPM package sits at the repository root (Open Exchange: "Place the module.xml file in the root of your project in
GitHub") and is iris/module.xml with every path under iris/; every path it names exists."""
import pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]


def module(path):
    return ET.parse(path).getroot().find("Document/Module")


def test_the_root_module_is_the_iris_module_with_its_paths_under_iris():
    root, iris = module(ROOT / "module.xml"), module(ROOT / "iris" / "module.xml")
    for tag in ("Name", "Version", "Description", "Keywords", "Packaging"):
        assert root.findtext(tag) == iris.findtext(tag), tag
    assert root.findtext("SourcesRoot") == "iris/" + iris.findtext("SourcesRoot")
    assert [r.get("Name") for r in root.findall("Resource")] == [r.get("Name") for r in iris.findall("Resource")]
    assert [("iris/" + f.get("Name"), f.get("Target"), f.get("Overlay")) for f in iris.findall("FileCopy")] == \
           [(f.get("Name"), f.get("Target"), f.get("Overlay")) for f in root.findall("FileCopy")]
    assert [(i.get("Class"), i.get("Method"), [a.text for a in i.findall("Arg")]) for i in root.findall("Invoke")] == \
           [(i.get("Class"), i.get("Method"), [a.text for a in i.findall("Arg")]) for i in iris.findall("Invoke")]


def test_every_path_the_root_module_names_exists():
    root = module(ROOT / "module.xml")
    assert (ROOT / root.findtext("SourcesRoot") / "Knos" / "Iris").is_dir()
    for f in root.findall("FileCopy"):
        assert (ROOT / f.get("Name")).exists(), f.get("Name")
