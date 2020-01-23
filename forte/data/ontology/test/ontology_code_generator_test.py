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
"""
    Tests for the module forte.data.ontology.ontology_code_generator
"""
import os
import sys
import pathlib
import unittest
import tempfile
import importlib
import warnings
from ddt import ddt, data

from forte.data.ontology.ontology_code_generator import (
    OntologyCodeGenerator
)
from forte.data.ontology.code_generation_exceptions import \
    DirectoryAlreadyPresentWarning, DuplicateEntriesWarning, \
    ImportOntologyNotFoundException, ParentEntryNotDeclaredException, \
    TypeNotDeclaredException, UnsupportedTypeException, \
    DuplicatedAttributesWarning


@ddt
class GenerateOntologyTest(unittest.TestCase):
    def setUp(self):
        self.generator = OntologyCodeGenerator()
        self.dir_path = None

    def tearDown(self):
        """
        Cleans up the generated files after test case if any. Only cleans up if
        generate_ontology passes successfully.
        """
        if self.dir_path is not None:
            self.generator.cleanup_generated_ontology(self.dir_path,
                                                      is_forced=True)

    @data(('example_ontology',
           ['ft/onto/example_import_ontology', 'ft/onto/example_ontology']),
          ('example_complex_ontology',
           ['ft/onto/example_complex_ontology']),
          ('example_multi_module_ontology',
           ['ft/onto/ft_module', 'custom/user/custom_module']))
    def test_generated_code(self, value):
        input_file_name, file_paths = value
        file_paths = sorted(file_paths)

        # read json and generate code in a file
        json_file_path = get_config_path(f'test_specs/{input_file_name}.json')
        folder_path = self.generator.generate(json_file_path,
                                              is_dry_run=True)
        self.dir_path = folder_path
        # record code
        generated_files = []
        for root, dirs, files in os.walk(folder_path):
            generated_files.extend([os.path.join(root, file)
                                    for file in files if file.endswith('.py')])
        generated_files = sorted(generated_files)

        exp_files = sorted([f"{os.path.join(folder_path, file)}.py"
                            for file in file_paths])

        self.assertCountEqual(generated_files, exp_files)

        dir_path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                'test_outputs')

        for i, generated_file in enumerate(generated_files):
            with open(generated_file, 'r') as f:
                generated_code = f.read()

            # assert if generated code matches with the expected code
            expected_code_path = os.path.join(dir_path, f'{file_paths[i]}.py')
            with open(expected_code_path, 'r') as f:
                expected_code = f.read()

            self.assertEqual(generated_code, expected_code)

    def test_dry_run_false(self):
        temp_dir = tempfile.mkdtemp()
        json_file_path = get_config_path(
            "test_specs/example_import_ontology.json")
        temp_filename = get_temp_filename(json_file_path, temp_dir)
        self.generator.generate(temp_filename, temp_dir, False)
        folder_path = temp_dir
        for name in ["ft", "onto", "example_import_ontology.py"]:
            self.assertTrue(name in os.listdir(folder_path))
            folder_path = os.path.join(folder_path, name)

    @data((True, 'test_duplicate_entry.json', DuplicateEntriesWarning),
          (True, 'test_duplicate_attribute.json', DuplicatedAttributesWarning),
          (False, 'example_ontology.json', ImportOntologyNotFoundException),
          (False, 'test_invalid_parent.json', ParentEntryNotDeclaredException),
          (False, 'test_invalid_attribute.json', TypeNotDeclaredException),
          (False, 'test_nested_item_type.json', UnsupportedTypeException),
          (False, 'test_no_item_type.json', TypeNotDeclaredException),
          (False, 'test_unknown_item_type.json', TypeNotDeclaredException))
    def test_warnings_errors(self, value):
        expected_warning, file, msg_type = value
        temp_dir = tempfile.mkdtemp()
        dirname = 'test_specs'
        filepath = os.path.join(dirname, file)
        json_file_name = get_config_path(filepath)
        temp_filename = get_temp_filename(json_file_name, temp_dir)
        if expected_warning:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                self.generator.generate(temp_filename, is_dry_run=True)
                self.assertEqual(len(w), 1)
                assert w[0].category, msg_type
        else:
            # TODO: make sure the exceptions are caught here
            print(file)
            with self.assertRaises(msg_type):
                self.generator.generate(temp_filename, is_dry_run=True)

    def test_directory_already_present(self):
        temp_dir = tempfile.mkdtemp()
        os.mkdir(os.path.join(temp_dir, "ft"))
        json_file_path = get_config_path(
            "test_specs/example_import_ontology.json")
        temp_filename = get_temp_filename(json_file_path, temp_dir)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.generator.generate(temp_filename, temp_dir, False)
            self.assertEqual(len(w), 1)
            assert w[0].category, DirectoryAlreadyPresentWarning

    def test_top_ontology_parsing_imports(self):
        temp_dir = tempfile.mkdtemp()
        temp_filename = os.path.join(temp_dir, 'temp.py')
        sys.path.append(temp_dir)
        with open(temp_filename, 'w') as temp_file:
            temp_file.write('import os.path\n'
                            'import os.path as os_path\n'
                            'from os import path\n')
        temp_module = importlib.import_module('temp')
        _, imports, _ = OntologyCodeGenerator.initialize_top_entries(
            temp_module)
        expected_imports = {"os.path": "os.path",
                            "os_path": "os.path",
                            "path": "os.path"}
        self.assertDictEqual(imports, expected_imports)


def get_config_path(filename):
    return str(pathlib.Path(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f'{filename}')).resolve())


def get_temp_filename(json_file_path, temp_dir):
    with open(json_file_path, 'r') as f:
        json_content = f.read()
    temp_filename = os.path.join(temp_dir, 'temp.json')
    with open(temp_filename, 'w') as temp_file:
        temp_file.write(json_content)
    return temp_filename
