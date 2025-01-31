"""Abstraction on top of PreflightResponse."""

import json


class PreflightParser:
    """Abstraction class on top of PreflightResponse."""

    def __init__(self, preflight_file):
        with open(preflight_file) as file:
            self.data = json.load(file)

    def list_top_level_files(self):
        """Collect all toplevel files."""
        return [file["filename"] for file in self.data.get("detected_toplevel_files", [])]

    def get_top_level_file_issues(self):
        """Collect all issues reported for toplevel files."""
        issues = {}
        for file in self.data.get("detected_toplevel_files", []):
            filename = file["filename"]
            file_issues = file.get("issues", [])
            issues[filename] = file_issues
        return issues

    def list_tex_files(self):
        """Collect all tex files."""
        return [file["filename"] for file in self.data.get("tex_files", [])]

    def get_tex_file_issues(self):
        """Collect all issues reported for tex files."""
        issues = {}
        for file in self.data.get("tex_files", []):
            filename = file["filename"]
            file_issues = file.get("issues", [])
            issues[filename] = file_issues
        return issues

    def collect_issues(self, filename):
        """Collect issues for the specified filename and append any issues from its tex_files entry."""
        issues = []
        top_level_issues = self.get_top_level_file_issues()
        tex_file_issues = self.get_tex_file_issues()

        if filename in top_level_issues:
            issues.extend(top_level_issues[filename])

        if filename in tex_file_issues:
            issues.extend(tex_file_issues[filename])

        return issues

    def tex_files_used_recursive(self, top_level_files, include_all_files=False):
        """Recursively collect all tex files for a given toplevel file."""

        def collect_files(filenames, visited):
            collected_files = set()
            for filename in filenames:
                if filename in visited:
                    continue
                visited.add(filename)
                for tex_file in self.data.get("tex_files", []):
                    if tex_file["filename"] == filename:
                        collected_files.add(tex_file["filename"])
                        if "used_tex_files" in tex_file:
                            collected_files.update(collect_files(tex_file["used_tex_files"], visited))
                        if include_all_files:
                            if "used_other_files" in tex_file:
                                collected_files.update(tex_file["used_other_files"])
                            if "used_bib_files" in tex_file:
                                collected_files.update(tex_file["used_bib_files"])
            return collected_files

        visited = set()
        used_files = set()
        for top_level_file in top_level_files:
            used_files.update(collect_files([top_level_file], visited))
        return list(used_files)

    def build_hierarchy(self, specified_top_level_files=None, include_all_files=False):
        """Create the hierarchy response."""

        def build_tree(filename, visited, used_files):
            if filename in visited:
                return None
            visited.add(filename)
            used_files.add(filename)
            node = {filename: {"issues": self.collect_issues(filename), "children": []}}
            for tex_file in self.data.get("tex_files", []):
                if tex_file["filename"] == filename:
                    if "used_tex_files" in tex_file:
                        for child_filename in tex_file["used_tex_files"]:
                            child_node = build_tree(child_filename, visited, used_files)
                            if child_node:
                                node[filename]["children"].append(child_node)
                    if include_all_files:
                        if "used_other_files" in tex_file:
                            for child_filename in tex_file["used_other_files"]:
                                node[filename]["children"].append({child_filename: {"issues": [], "children": []}})
                                used_files.add(child_filename)
                        if "used_bib_files" in tex_file:
                            for child_filename in tex_file["used_bib_files"]:
                                node[filename]["children"].append({child_filename: {"issues": [], "children": []}})
                                used_files.add(child_filename)
            return node

        hierarchy = {}
        visited = set()
        used_files = set()

        top_level_files = specified_top_level_files if specified_top_level_files else self.list_top_level_files()

        for top_level_file in top_level_files:
            hierarchy.update(build_tree(top_level_file, visited, used_files))

        all_files = set(self.list_top_level_files() + self.list_tex_files())
        not_selected_files = list(all_files - used_files)
        # detected_top_level_files = self.data.get('tex_files', [])
        detected_top_level_files = self.data.get("detected_toplevel_files", [])
        return {
            "detected_top_level_files": detected_top_level_files,
            "document_tree": hierarchy,
            "used_files": list(used_files),
            "not_selected": not_selected_files,
        }
