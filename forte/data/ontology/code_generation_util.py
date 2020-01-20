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
import os
from abc import ABC
from collections import OrderedDict
from typing import Optional, Any, List


class Config:
    indent: int = 4
    line_break: str = os.linesep


def indent(level: int) -> str:
    return ' ' * Config.indent * level


def indent_line(line: str, level: int) -> str:
    return f"{indent(level)}{line}" if line else ''


def indent_code(code_lines: List[str], level: int = 0) -> str:
    lines = []
    for code in code_lines:
        lines.extend(code.split(Config.line_break) if code is not None else [])
    return Config.line_break.join([indent_line(line, level) for line in lines])


def empty_lines(num: int):
    return ''.join([Config.line_break] * num)


def getter(name: str, level: int):
    lines = [
        ("@property", 0),
        (f"def {name}(self):", 0),
        (f"return self._{name}", 1),
    ]
    return indent_code([indent_line(*line) for line in lines], level)


def setter(name: str, level: int):
    lines = [
        (f"def set_{name}(self):", 0),
        (f"return self._{name}", 1),
    ]
    return indent_code([indent_line(*line) for line in lines], level)


def appender(name: str, level: int):
    lines = [
        (f"def add_{name}(self):", 0),
        (f"self.{name}.add(a_{name})", 1),
    ]
    return indent_code([indent_line(*line) for line in lines], level)


class Item:
    def __init__(self, name: str, description: Optional[str]):
        self.name: str = name
        self.description: Optional[str] = description

    def to_description(self, level: int) -> Optional[str]:
        if self.description is not None:
            return indent_code([self.description], level)
        return None

    def to_code(self, level: int) -> str:
        raise NotImplementedError


class Property(Item, ABC):
    def __init__(self,
                 name: str,
                 type_str: str,
                 description: Optional[str] = None,
                 default: Any = None):
        super().__init__(name, description)
        self.type_str = type_str
        self.default = default

    def to_property_access_functions(self, level):
        """ Some functions to define how to access the property values, such
        as getters, setters, len, etc.
        Args:
            level: The indentation level to format these functions.

        Returns: The access code generated for this property
        """
        name = self.name
        lines = [("@property", 0),
                 (f"def {name}(self):", 0),
                 (f"return self._{name}", 1),
                 (empty_lines(0), 0),
                 (f"def set_{name}(self, {name}: {self.to_code(0)}):", 0),
                 (f"self.set_fields(_{name}={self.to_field_value()})", 1),
                 (empty_lines(0), 0)]
        return indent_code([indent_line(*line) for line in lines], level)

    def to_init_code(self, level: int) -> str:
        return indent_line(f"self._{self.name}: {self.to_code(0)} = "
                           f"{repr(self.default)}", level)

    def to_description(self, level: int) -> Optional[str]:
        if self.description is not None and self.description.strip() != '':
            type_str = f'{self.to_code(0)}'
            type_str = f' ({type_str})' if type_str.strip() != '' else type_str
            return indent_line(f"{self.name}{type_str}: "
                               f"{self.description}", level)
        return None

    def to_field_value(self):
        raise NotImplementedError


class ClassAttributeProperty(Property):
    def to_code(self, level: int = 0) -> str:
        return self.type_str

    def to_init_code(self, level: int) -> str:
        type_code = f'{self.to_code(0)}'
        type_ = f': {type_code}' if type_code.strip() != '' else ''
        return indent_line(f"{self.name}{type_} = {self.default}", level)

    def to_field_value(self):
        pass


class PrimitiveProperty(Property):
    TYPES = {'int', 'float', 'str', 'bool'}

    def to_code(self, level: int = 0) -> str:
        return f"typing.Optional[{self.type_str}]"

    def to_field_value(self):
        if self.type_str in self.TYPES:
            return self.name
        return f"{self.name}.tid"


class CompositeProperty(Property):
    TYPES = {'List'}

    def __init__(self,
                 name: str,
                 type_str: str,
                 item_type: str,
                 description: Optional[str] = None,
                 default: Any = None):
        super().__init__(name, type_str, description, default)
        self.item_type = item_type

    def to_property_access_functions(self, level):
        code = super(CompositeProperty, self).to_property_access_functions(
            level)
        l

    def to_field_value(self):
        item_value_str = PrimitiveProperty('item',
                                           self.item_type).to_field_value()
        return f"[{item_value_str} for item in {self.name}]"


class DefinitionItem(Item):
    def __init__(self, name: str,
                 class_type: str,
                 init_args: Optional[str] = None,
                 properties: Optional[List[Property]] = None,
                 class_attributes: Optional[List[Property]] = None,
                 description: Optional[str] = None):
        super().__init__(name, description)
        self.class_type = class_type
        self.properties: List[Property] = \
            [] if properties is None else properties
        self.class_attributes = [] if class_attributes is None \
            else class_attributes
        self.description = description if description else None
        self.init_args = init_args if init_args is not None else ''
        self.init_args = self.init_args.replace('=', ' = ')

    def to_init_code(self, level: int) -> str:
        return indent_line(f"def __init__(self, {self.init_args}):", level)

    def to_code(self, level: int) -> str:
        super_args = ', '.join([item.split(':')[0].strip()
                                for item in self.init_args.split(',')])
        raw_desc = self.to_description(1)
        desc: str = '' if raw_desc is None else raw_desc
        lines = [
            empty_lines(1),
            f"__all__.extend('{self.name}')",
            empty_lines(1),
            f"class {self.name}({self.class_type}):",
        ]
        lines += [desc] if desc.strip() else []
        lines += [item.to_init_code(1) for item in self.class_attributes]
        lines += [empty_lines(0)]
        lines += [self.to_init_code(1),
                  indent_line(f"super().__init__({super_args})", 2)]
        lines += [item.to_init_code(2) for item in self.properties]
        lines += [empty_lines(0)]
        lines += [item.to_getter_setter_code(1) for item in self.properties]

        return indent_code(lines, level)

    @staticmethod
    def to_item_descs(items, title):
        item_descs = [item.to_description(0) for item in items]
        item_descs = [item for item in item_descs if item is not None]
        if len(item_descs) > 0:
            item_descs = [indent_line(title, 1)] + \
                         [indent_line(desc, 2) for desc in item_descs]
        return item_descs

    def to_description(self, level: int) -> Optional[str]:
        class_desc = [] if self.description is None else [self.description]
        item_descs = self.to_item_descs(self.properties, 'Args:')
        att_descs = self.to_item_descs(self.class_attributes, 'Attr:')
        descs = class_desc + item_descs + att_descs
        if len(descs) == 0:
            return ""
        quotes = indent_line('"""', 0)
        return indent_code([quotes] + descs + [quotes], level)


class FileItem:
    def __init__(self,
                 entry_item: DefinitionItem,
                 entry_file: str,
                 ignore_errors: Optional[List[str]],
                 description: Optional[str],
                 imports: Optional[List[str]]):
        self.description = description
        self.ignore_errors = [] if not ignore_errors else ignore_errors
        self.imports = [] if not imports else list(set(imports))
        self.entry_item = entry_item
        self.entry_file_exists = os.path.exists(entry_file)

    def to_code(self, level: int) -> str:
        lines: List[str] = []
        if not self.entry_file_exists:
            lines = [self.to_description(0),
                     self.to_import_code(0),
                     empty_lines(1), '__all__ = []']
        lines.append(self.entry_item.to_code(0))
        return indent_code(lines, level)

    def to_description(self, level):
        quotes = '"""'
        lines = self.ignore_errors + [quotes, self.description, quotes]
        return indent_code(lines, level)

    def to_import_code(self, level):
        imports_set: OrderedDict[str] = {}
        for import_ in sorted(self.imports):
            imports_set[f"import {import_}"] = None
        return indent_code(list(imports_set), level)
