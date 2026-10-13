# Alfred Workflows

A collection of Alfred workflows by [Harshal Ranjhani](https://harshalranjhani.in).

## Workflows

| Workflow | Description | Location |
| --- | --- | --- |
| [Night Shift](alfred-night-shift/) | Toggle macOS Night Shift and adjust colour temperature from Alfred. | Included in this repository |
| [SSH Manager](https://github.com/harshalranjhani/alfred-ssh-manager) | Alfred SSH Manager workflow. | Git submodule: [`alfred-ssh-manager/`](alfred-ssh-manager/) |

## Install

For Night Shift, [download the workflow](alfred-night-shift/dist/Night%20Shift.alfredworkflow?raw=true), open it, and choose **Import** in Alfred. See the [Night Shift README](alfred-night-shift/README.md) for commands and requirements.

For SSH Manager, follow the installation instructions in its [repository](https://github.com/harshalranjhani/alfred-ssh-manager).

## Repository layout

Workflows hosted here each live in their own folder at the repository root, with their source, documentation, and packaged workflow together. SSH Manager is linked as a Git submodule at the root, so it also appears in the GitHub file list. Its source is maintained in its own repository.

To clone this collection with submodule contents:

```sh
git clone --recurse-submodules https://github.com/harshalranjhani/alfred-workflows.git
```

For an existing clone, run `git submodule update --init --recursive`.
