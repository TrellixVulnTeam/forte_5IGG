# Copyright 2019 The Forte Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import itertools as it
import logging
import os
import warnings
from abc import ABC
from pathlib import Path
from typing import Optional, Any, List, Dict, Set, Tuple, cast
from numpy import ndarray

from forte.data.ontology.code_generation_exceptions import (
    CodeGenerationException,
    OntologyGenerationWarning,
)
from forte.data.ontology.ontology_code_const import (
    SUPPORTED_PRIMITIVES,
    NON_COMPOSITES,
    COMPOSITES,
    Config,
    get_ignore_error_lines,
    AUTO_GEN_SIGNATURE,
    AUTO_GEN_FILENAME,
)
from forte.data.ontology.utils import split_file_path


class ImportManager:
    r"""A naive implementation that records import strings and imported names
    to be used. Mainly used to avoid import name conflicts such as:
       -- from user.module import token
       -- from system.module import token
    """

    def __init__(
        self, root: Optional["ImportManager"], module_name: Optional[str]
    ):
        self.__root = root
        self.__module_name = module_name
        self.__import_statements: List[str] = []
        # Defining names imported by this module.
        self.__imported_names: Dict[str, str] = {}
        # Defining names to be added by this generation module
        self.__defining_names: Dict[str, str] = {}
        self.__short_name_pool: Set[str] = set()
        self.__fix_modules = False

    def fix_modules(self):
        self.__fix_modules = True

    def is_known_name(self, full_class_name):
        """
        Check whether the class name can be used. It will check the class name
        in both the top manager or the current manager.

        Args:
            full_class_name: The name to be check.

        Returns: True if the class_name can be used, which means it is either
            imported or it is of a primitive type.

        """
        return (
            full_class_name in NON_COMPOSITES
            or full_class_name in COMPOSITES
            or self.is_imported(full_class_name)
            or full_class_name in self.__defining_names
        )

    def is_imported(self, class_name):
        """
        Check whether this `class_name` is already imported here in the module.
        Args:
            class_name: The name to be checked for importing.

        Returns: True if the class_name is imported.

        """
        if class_name in self.__imported_names:
            return True
        elif self.__root is None:
            return False
        else:
            if self.__root.is_imported(class_name) and not self.__fix_modules:
                self.add_object_to_import(class_name)
                return True

    def all_stored(self):
        return self.__imported_names.items()

    def get_name_to_use(self, full_name):
        if full_name in SUPPORTED_PRIMITIVES:
            return full_name

        if full_name in self.__defining_names:
            return self.__defining_names[full_name]

        if self.is_imported(full_name):
            return self.__imported_names[full_name]

    def get_import_statements(self):
        return sorted(self.__import_statements)

    def create_import_statement(self, full_name: str, as_name: str):
        if full_name not in NON_COMPOSITES:
            parts = full_name.split(".")
            class_name = parts[-1]

            if len(parts) > 1:
                module_name = ".".join(parts[:-1])

                if (
                    self.__module_name is None
                    or not module_name == self.__module_name
                ):
                    # No need to import classes in the same module
                    if class_name == as_name:
                        import_statement = (
                            f"from {module_name} " f"import {class_name}"
                        )
                    else:
                        import_statement = (
                            f"from {module_name} "
                            f"import {class_name} as {as_name}"
                        )

                    self.__import_statements.append(import_statement)
            else:
                if class_name == as_name:
                    import_statement = f"import {class_name}"
                else:
                    import_statement = f"import {class_name} as {as_name}"
                self.__import_statements.append(import_statement)

    def __find_next_available(self, class_name) -> str:
        counter = 0
        while True:
            as_name = f"{class_name}_{counter}"
            counter += 1
            if as_name not in self.__short_name_pool:
                break
        return as_name

    def __assign_as_name(self, full_name) -> str:
        class_name = full_name.split(".")[-1]
        if class_name not in self.__short_name_pool:
            self.__short_name_pool.add(class_name)
            return class_name
        else:
            as_name = self.__find_next_available(class_name)
            self.__short_name_pool.add(as_name)
            return as_name

    def add_defining_objects(self, full_name: str):
        if self.__fix_modules:
            # After fixing the modules, we should not add objects for import.
            raise CodeGenerationException(
                f"The module [{self.__module_name}] is fixed, cannot add "
                f"more objects."
            )

        if full_name not in self.__defining_names:
            class_name = full_name.split(".")[-1]
            if class_name not in self.__short_name_pool:
                self.__short_name_pool.add(class_name)
            else:
                warnings.warn(
                    f"Re-declared a new class named [{class_name}]"
                    ", which is probably used in import.",
                    OntologyGenerationWarning,
                )
            self.__defining_names[full_name] = class_name

    def add_object_to_import(self, full_name: str):
        if self.__fix_modules:
            # After fixing the modules, we should not add objects for import.
            raise CodeGenerationException(
                f"The module [{self.__module_name}] is fixed, cannot add "
                f"more objects."
            )

        if full_name not in self.__imported_names:
            if full_name not in SUPPORTED_PRIMITIVES:
                as_name = self.__assign_as_name(full_name)
                self.__imported_names[full_name] = as_name
                self.create_import_statement(full_name, as_name)


class ImportManagerPool:
    """
    Holds import managers. The top_manager stores the default imports
    guaranteed by Forte's system ontology. The additional import managers are
    further populated by analyzing the generated code.
    """

    def __init__(self):
        self.__root_manager = ImportManager(None, None)
        self.__managers: Dict[str, ImportManager] = {}
        self.__default_imports: List[str] = []

    def add_default_import(self, full_name: str):
        self.__default_imports.append(full_name)

    @property
    def root(self) -> ImportManager:
        return self.__root_manager

    def get(self, module_name: str) -> ImportManager:
        if module_name in self.__managers:
            return self.__managers[module_name]
        else:
            nm = ImportManager(self.__root_manager, module_name)
            for full_name in self.__default_imports:
                nm.add_object_to_import(full_name)

            self.__managers[module_name] = nm
            return nm

    def fix_all_modules(self):
        self.__root_manager.fix_modules()
        for im in self.__managers.values():
            im.fix_modules()


def indent(level: int) -> str:
    return " " * Config.indent * level


def indent_line(line: str, level: int) -> str:
    return f"{indent(level)}{line}" if line else ""


def indent_code(
    code_lines: List[Optional[str]], level: int = 0, is_line_break: bool = True
) -> str:
    lines = []

    for code in code_lines:
        if code is None:
            continue
        if code == "":
            lines.append("")
        else:
            lines.extend(
                code.split(Config.line_break) if code is not None else []
            )
    ending = "\n" if is_line_break else ""
    return (
        Config.line_break.join([indent_line(line, level) for line in lines])
        + ending
    )


class EntryName:
    def __init__(self, entry_name: str):
        entry_splits = entry_name.split(".")
        self.filename, self.name = entry_splits[-2:]
        self.pkg = ".".join(entry_splits[0:-2])
        self.pkg_dir = self.pkg.replace(".", "/")
        self.module_name: str = f"{self.pkg}.{self.filename}"
        self.class_name: str = entry_name


class Item:
    def __init__(self, name: str, description: Optional[str]):
        self.name: str = name
        self.description: Optional[str] = description

    @property
    def field_name(self):
        return self.name

    def to_description(self, level: int) -> Optional[str]:
        if self.description is not None:
            return indent_code([self.description], level)
        # Returning a empty string will generate a placeholder for
        # the description.
        return ""


class Property(Item, ABC):
    def __init__(
        self,
        import_manager: ImportManager,
        name: str,
        type_str: str,
        description: Optional[str] = None,
        default_val: Any = None,
    ):
        super().__init__(name, description)
        self.type_str = type_str
        self.default_val = default_val
        self.import_manager: ImportManager = import_manager
        self.import_manager.add_object_to_import(self.type_str)

    def to_declaration(self, level: int):
        s = f"{self.field_name}: {self.internal_type_str()}"
        return indent_line(s, level)

    def internal_type_str(self) -> str:
        raise NotImplementedError

    def default_value(self) -> str:
        raise NotImplementedError

    def to_init_code(self, level: int) -> str:
        return indent_line(
            f"self.{self.field_name}: "
            f"{self.internal_type_str()} = "
            f"{self.default_value()}",
            level,
        )

    def to_description(self, level: int) -> Optional[str]:
        desc = f"{self.field_name} ({self.internal_type_str()}):"

        if self.description is not None and self.description.strip() != "":
            desc += f"\t{self.description}"
            return indent_line(desc, level)
        return indent_line(desc, level)

    def to_field_value(self):
        raise NotImplementedError


class ClassTypeDefinition:
    def __init__(
        self, name: str, type_str: str, description: Optional[str] = None
    ):
        self.name = name
        self.type_str = type_str
        self.description = description

    def to_code(self, level: int) -> str:
        return indent_code([f"{self.name} = {self.type_str}"], level, False)

    def to_field_value(self):
        pass


class NonCompositeProperty(Property):
    def __init__(
        self,
        import_manager: ImportManager,
        name: str,
        type_str: str,
        description: Optional[str] = None,
        default_val: Any = None,
        self_ref: bool = False,
    ):
        super().__init__(
            import_manager, name, type_str, description, default_val
        )

        # Primitive type will use optional in type string, so we add the
        # optional here.
        self.option_type = "typing.Optional"
        import_manager.add_object_to_import(self.option_type)

        self.is_forte_type = import_manager.is_imported(type_str)
        self.self_ref = self_ref

    def internal_type_str(self) -> str:
        option_type = self.import_manager.get_name_to_use(self.option_type)
        type_str = self.import_manager.get_name_to_use(self.type_str)
        if self.self_ref:
            type_str = f"'{type_str}'"
        return f"{option_type}[{type_str}]"

    def default_value(self) -> str:
        return repr(self.default_val)

    def to_field_value(self):
        return self.name


class NdArrayProperty(Property):
    """
    NdArrayProperty accepts parsed properties of NdArray and
    instructs import manager to import and instanciate FNdArray
    as default value in the generated code.
    """

    def __init__(
        self,
        import_manager: ImportManager,
        name: str,
        ndarray_dtype: Optional[str] = None,
        ndarray_shape: Optional[List[int]] = None,
        description: Optional[str] = None,
        default_val: Optional[ndarray] = None,
    ):
        self.type_str = "forte.data.ontology.core.FNdArray"
        super().__init__(
            import_manager,
            name,
            self.type_str,
            description=description,
            default_val=default_val,
        )
        self.ndarray_dtype: Optional[str] = ndarray_dtype
        self.ndarray_shape: Optional[List[int]] = ndarray_shape

    def internal_type_str(self) -> str:
        type_str = self.import_manager.get_name_to_use(self.type_str)
        return f"{type_str}"

    def default_value(self) -> str:
        if self.ndarray_dtype is None:
            return f"FNdArray(shape={self.ndarray_shape}, dtype={self.ndarray_dtype})"
        else:
            return f"FNdArray(shape={self.ndarray_shape}, dtype='{self.ndarray_dtype}')"

    def _full_class(self):
        item_type = self.import_manager.get_name_to_use(self.type_str)
        return item_type

    def to_field_value(self):
        return self.name


class DictProperty(Property):
    def __init__(
        self,
        import_manager: ImportManager,
        name: str,
        key_type: str,
        value_type: str,
        description: Optional[str] = None,
        default_val: Any = None,
        self_ref: bool = False,
    ):
        if not key_type == "str":
            # This string value constraint is to conform with JSON format
            #  requirement: https://www.json.org/json-en.html
            raise CodeGenerationException(
                f"Dictionary keys can only be string values, find {key_type} "
                f"at {name}."
            )

        self.value_is_forte_type = import_manager.is_imported(value_type)
        type_str = (
            "forte.data.ontology.core.FDict"
            if self.value_is_forte_type
            else "typing.Dict"
        )
        super().__init__(
            import_manager,
            name,
            type_str,
            description=description,
            default_val=default_val,
        )
        self.key_type: str = key_type
        self.value_type: str = value_type
        self.self_ref: bool = self_ref

    def internal_type_str(self) -> str:
        # option_type = self.import_manager.get_name_to_use('typing.Optional')
        return f"{self._full_class()}"

    def default_value(self) -> str:
        if self.type_str == "typing.Dict":
            return "dict()"
        else:
            return "FDict(self)"

    def _full_class(self) -> str:
        composite_type = self.import_manager.get_name_to_use(self.type_str)
        key_type = self.import_manager.get_name_to_use(self.key_type)
        value_type = self.import_manager.get_name_to_use(self.value_type)
        if self.self_ref:
            value_type = f"'{value_type}'"

        return f"{composite_type}[{key_type}, {value_type}]"

    def to_field_value(self):
        return self.name


class ListProperty(Property):
    def __init__(
        self,
        import_manager: ImportManager,
        name: str,
        item_type: str,
        description: Optional[str] = None,
        default_val: Any = None,
        self_ref: bool = False,
    ):
        self.value_is_forte_type = import_manager.is_imported(item_type)
        type_str = (
            "forte.data.ontology.core.FList"
            if self.value_is_forte_type
            else "typing.List"
        )
        super().__init__(
            import_manager,
            name,
            type_str,
            description=description,
            default_val=default_val,
        )
        self.item_type: str = item_type
        self.self_ref: bool = self_ref

    def internal_type_str(self) -> str:
        # option_type = self.import_manager.get_name_to_use('typing.Optional')
        return f"{self._full_class()}"

    def default_value(self) -> str:
        if self.type_str == "typing.List":
            return "[]"
        else:
            return "FList(self)"

    def _full_class(self):
        composite_type = self.import_manager.get_name_to_use(self.type_str)
        item_type = self.import_manager.get_name_to_use(self.item_type)
        if self.self_ref:
            item_type = f"'{item_type}'"

        return f"{composite_type}[{item_type}]"

    def to_field_value(self):
        return self.name


class EntryDefinition(Item):
    def __init__(
        self,
        name: str,
        class_type: str,
        init_args: Optional[str] = None,
        properties: Optional[List[Property]] = None,
        class_attributes: Optional[List[ClassTypeDefinition]] = None,
        description: Optional[str] = None,
    ):
        super().__init__(name, description)
        self.class_type = class_type
        self.properties: List[Property] = (
            [] if properties is None else properties
        )
        self.class_attributes = (
            [] if class_attributes is None else class_attributes
        )
        self.description = description if description else None
        self.init_args = init_args if init_args is not None else ""
        self.init_args = self.init_args.replace("=", " = ")

    def to_init_code(self, level: int) -> str:
        return indent_line(f"def __init__(self, {self.init_args}):", level)

    def to_property_code(self, level: int) -> str:
        lines = []
        for p in self.properties:
            lines.append(p.to_declaration(0))
        return indent_code(
            [indent_line(line, 0) for line in lines], level, False
        )

    def to_class_attribute_code(self, level: int):
        lines = [item.to_code(0) for item in self.class_attributes]
        return indent_code(
            [indent_line(line, 0) for line in lines], level, False
        )

    def to_code(self, level: int) -> str:
        super_args = ", ".join(
            [item.split(":")[0].strip() for item in self.init_args.split(",")]
        )
        raw_desc = self.to_description(1)
        desc: str = "" if raw_desc is None else raw_desc
        lines: List[Optional[str]] = [
            "",
            "",
            "@dataclass",
            f"class {self.name}({self.class_type}):",
        ]

        lines += [desc] if desc.strip() else []

        lines.append("")

        property_code = self.to_property_code(1)
        if property_code:
            lines.append(property_code)
            lines.append("")

        class_attr_code = self.to_class_attribute_code(1)
        if class_attr_code:
            lines.append(class_attr_code)
            lines.append("")

        lines += [
            self.to_init_code(1),
            indent_line(f"super().__init__({super_args})", 2),
        ]
        lines += [item.to_init_code(2) for item in self.properties]
        lines += [""]

        return indent_code(lines, level, False)

    @staticmethod
    def to_item_descs(items, title):
        item_descs = [item.to_description(0) for item in items]
        item_descs = [item for item in item_descs if item is not None]
        if len(item_descs) > 0:
            item_descs = [indent_line(title, 0)] + [
                indent_line(desc, 1) for desc in item_descs
            ]
        return item_descs

    def to_description(self, level: int) -> Optional[str]:
        class_desc = [] if self.description is None else [self.description + ""]
        item_descs = self.to_item_descs(self.properties, "Attributes:")

        descs = class_desc + item_descs
        if len(descs) == 0:
            return ""
        quotes = indent_line('"""', 0)
        return indent_code([quotes] + descs + [quotes], level, False)


class ModuleWriter:
    """
    A writer to write entry definitions to a file.
    """

    def __init__(self, module_name: str, import_managers: ImportManagerPool):
        self.module_name = module_name
        self.source_file: Path

        self.description: Optional[str] = None
        self.import_managers: ImportManagerPool = import_managers
        self.entries: List[Tuple[EntryName, EntryDefinition]] = []

        pkg, self.file_name = self.module_name.rsplit(".", 1)
        self.pkg_dir = pkg.replace(".", "/")

    def set_description(self, description: str):
        self.description = description

    def add_entry(self, entry_name: EntryName, entry_item: EntryDefinition):
        self.entries.append((entry_name, entry_item))

    def make_module_dirs(
        self,
        tempdir: str,
        destination: str,
        namespace_depth: int,
    ):
        """
        Create entry subdirectories with .generated file to indicate the
         subdirectory is created by this procedure. No such file will be added
         if the directory already exists.

        Args:
            tempdir: A temp directory to create the structure, code will be
              first generated here.
            destination: The destination directory where the code should be
              placed
            namespace_depth: set an integer argument namespace_depth to allow
              customized number of levels of namespace packaging.
              The generation of __init__.py for all the directory
              levels above namespace_depth will be disabled.
              For example, if we have an ontology level1.levle2.level3.
              something and namespace_depth=2, then we remove __init__.py
              under level1 and level1/level2 while keeping __init__.py under
              level1/level2/level3.
              When namespace_depth<=0, we just disable namespace packaging
              and include __init__.py in all directory levels.
        Returns:
        """
        entry_dir_split = split_file_path(self.pkg_dir)

        rel_dir_paths = it.accumulate(entry_dir_split, os.path.join)
        count = 1
        for rel_dir_path in rel_dir_paths:
            temp_path = os.path.join(tempdir, rel_dir_path)
            if not os.path.exists(temp_path):
                os.mkdir(temp_path)

            dest_path = os.path.join(destination, rel_dir_path)
            dest_path_exists = os.path.exists(dest_path)
            if not dest_path_exists:
                Path(os.path.join(temp_path, AUTO_GEN_FILENAME)).touch()

            # Create init file
            if count > namespace_depth:
                if not dest_path_exists:
                    init_file_path = os.path.join(temp_path, "__init__.py")
                    with open(
                        init_file_path, "w", encoding="utf-8"
                    ) as init_file:
                        init_file.write(f"# {AUTO_GEN_SIGNATURE}\n")
            count += 1

    def write(
        self,
        tempdir: str,
        destination: str,
        namespace_depth: int,
    ):
        """
        Write the entry information to file.

        Args:
            tempdir: A temporary directory for writing intermediate files.
            destination: The actual folder to place the generated code.
            namespace_depth: set an integer argument namespace_depth to allow
              customized number of levels of namespace packaging.
              The generation of __init__.py for all the directory
              levels above namespace_depth will be disabled.
              For example, if we have an ontology level1.levle2.level3.
              something and namespace_depth=2, then we remove __init__.py
              under level1 and level1/level2 while keeping __init__.py under
              level1/level2/level3.
              When namespace_depth<=0, we just disable namespace packaging
              and include __init__.py in all directory levels.
        Returns:

        """

        self.make_module_dirs(tempdir, destination, namespace_depth)
        full_path = os.path.join(tempdir, self.pkg_dir, self.file_name) + ".py"

        with open(full_path, "w", encoding="utf-8") as f:
            # Write header.
            f.write(self.to_header(0))
            for entry_name, entry_item in self.entries:
                logging.info("Writing class: %s", entry_name.class_name)
                f.write(entry_item.to_code(0))

    def to_header(self, level: int) -> str:
        all_first_line = indent_line("__all__ = [", 0)
        all_mid_lines = indent_code(
            [f'"{en.name}",' for en, ei in self.entries], 1, False
        )
        all_last_line = indent_line("]", 0)

        lines = [
            self.to_description(0),
            self.to_import_code(0),
            all_first_line,
            all_mid_lines,
            all_last_line,
        ]
        return indent_code(lines, level)

    def to_description(self, level):
        quotes = '"""'
        lines = get_ignore_error_lines(str(self.source_file)) + [
            quotes,
            self.description,
            quotes,
        ]
        return indent_code(lines, level)

    def to_import_code(self, level):
        return indent_code(
            self.import_managers.get(self.module_name).get_import_statements(),
            level,
        )


class ModuleWriterPool:
    def __init__(self, import_managers: ImportManagerPool):
        self.__module_writers: Dict[str, ModuleWriter] = {}
        self.__import_managers = import_managers

    def get(self, module_name: str) -> ModuleWriter:
        if module_name in self.__module_writers:
            return self.__module_writers[module_name]
        else:
            mw = ModuleWriter(module_name, self.__import_managers)
            self.__module_writers[module_name] = mw
            return mw

    def writers(self):
        return self.__module_writers.values()


class EntryTreeNode:
    def __init__(self, name: str):
        self.__children: List[EntryTreeNode] = []
        self.__parent: Optional[EntryTreeNode] = None
        self.name: str = name
        self.attributes: Set[Tuple[str, str]] = set()

    def __repr__(self):
        r"""for printing purpose."""
        attr_str = ", ".join(str(a) for a in self.attributes)
        return self.name + ": " + attr_str

    @property
    def children(self) -> "List[EntryTreeNode]":
        return self.__children

    @property
    def parent(self) -> "EntryTreeNode":
        if self.__parent is None:
            raise ValueError("No parent for this node, probably root")
        return self.__parent

    @parent.setter
    def parent(self, value):
        self.__parent = value


class EntryTree:
    r"""
    A tree structure based on the parent-children relations of the entries.
    """

    def __init__(self):
        self.root = EntryTreeNode("root")

    def add_node(
        self,
        curr_entry_name: str,
        parent_entry_name: str,
        curr_entry_attr: Set[Tuple[str, str]],
    ):
        r"""Add a tree node with `curr_entry_name` as a child to
        `parent_entry_name` in the tree, the attributes `curr_entry_attr`
        would be added to the tree node attributes.

        Args:
            curr_entry_name: the type name of the node to be added.
            parent_entry_name: the type name of the parent of the node to be
                added.
            curr_entry_attr: the attributes of the node to be added.

        Returns:

        """
        found_node = search(self.root, curr_entry_name)
        if found_node is None:
            curr_entry_node = EntryTreeNode(curr_entry_name)
            curr_entry_node.attributes = curr_entry_attr
            parent_in_tree = search(self.root, parent_entry_name)
            if parent_in_tree is None:
                parent_in_tree = EntryTreeNode(parent_entry_name)
                self.root.children.append(parent_in_tree)
                parent_in_tree.parent = self.root
            parent_in_tree.children.append(curr_entry_node)
            curr_entry_node.parent = parent_in_tree
        else:
            found_node.attributes = curr_entry_attr

    def collect_parents(self, node_dict: Dict[str, Set[str]]):
        r"""Collect all the parent nodes for all the nodes in the `node_dict`
        and add the types and attributes of these parent nodes to `node_dict`.

        Args:
            node_dict: the nodes dictionary of nodes to collect parent nodes
                for. The entry represented by nodes in this dictionary do not store
                type information of its attributes. This dictionary does not store
                the type information of the nodes.

        """
        input_node_dict = node_dict.copy()
        for node_name in input_node_dict.keys():
            found_node = search(self.root, search_node_name=node_name)
            if found_node is not None:
                while found_node.parent.name != "root":
                    node_dict[found_node.parent.name] = set(
                        val[0] for val in found_node.parent.attributes
                    )
                    found_node = found_node.parent

    def todict(self) -> Dict[str, Any]:
        r"""Dump the EntryTree structure to a dictionary.

        Returns:
            dict: A dictionary storing the EntryTree.
        """

        def node_to_dict(node: EntryTreeNode):
            return (
                None
                if not node
                else {
                    "name": node.name,
                    "attributes": list(node.attributes),
                    "children": [
                        node_to_dict(child) for child in node.children
                    ],
                }
            )

        return node_to_dict(self.root)

    def fromdict(
        self, tree_dict: Dict[str, Any], parent_entry_name: Optional[str] = None
    ) -> Optional["EntryTree"]:
        r"""Load the EntryTree structure from a dictionary.

        Args:
            tree_dict: A dictionary storing the EntryTree.
            parent_entry_name: The type name of the parent of the node to be
                built. Default value is None.
        """
        if not tree_dict:
            return None

        if parent_entry_name is None:
            self.root = EntryTreeNode(name=tree_dict["name"])
            self.root.attributes = set(
                cast(Tuple[str, str], tuple(attr))
                for attr in tree_dict["attributes"]
            )
        else:
            self.add_node(
                curr_entry_name=tree_dict["name"],
                parent_entry_name=parent_entry_name,
                curr_entry_attr=set(
                    cast(Tuple[str, str], tuple(attr))
                    for attr in tree_dict["attributes"]
                ),
            )
        for child in tree_dict["children"]:
            self.fromdict(child, tree_dict["name"])
        return self


def search(node: EntryTreeNode, search_node_name: str):
    if node.name == search_node_name:
        return node

    for child in node.children:
        tmp = search(child, search_node_name)
        if tmp:
            return tmp


def traverse(node: EntryTreeNode, path: List[str]):
    path.append(repr(node))
    if len(node.children) == 0:
        print(path)
        path.pop()
    else:
        for child in node.children:
            traverse(child, path)
        path.pop()
