# image-toolkit

Zero-dependency Node.js utility for managing folders of images.
Requires Node.js (no `npm install` needed).

Supported formats: `.jpg` `.jpeg` `.png` `.gif` `.webp` `.bmp`

## Usage

```
node toolkit.js <command> <folder> [options]
```

### Commands

**stats** — summarize a folder
```
node toolkit.js stats <folder> [-r]
```
Counts by file type, total size, most common resolutions, largest files.

**duplicates** — find exact duplicate images (SHA-256 content hashing)
```
node toolkit.js duplicates <folder> [-r] [--delete]
```
Dry run by default. `--delete` removes the extra copies, keeping the first
file of each group and printing what it removed.

**rename** — bulk rename images in a folder
```
node toolkit.js rename <folder> --pattern "photo_{n}" [--start N] [--apply]
```
Dry run by default; `--apply` executes. Tokens:
- `{n}` sequence number (start at 1, or `--start N`)
- `{Y}` `{m}` `{d}` — current date

Extensions are preserved; illegal Windows filename characters are replaced;
name collisions get `_1`, `_2`, ... appended automatically.

**organize** — move images into subfolders
```
node toolkit.js organize <folder> [-r] [--by-ext] [--apply]
```
Default sorts into `YYYY-MM` folders by file modification date.
`--by-ext` sorts into type folders (`png`, `jpg`, ...).
Dry run by default; `--apply` executes. Collisions never overwrite.

### Options

| Flag | Effect |
|------|--------|
| `-r`, `--recursive` | include subfolders |
| `--apply` | execute changes (rename/organize) |
| `--delete` | remove duplicate files |
| `-h`, `--help` | show help |

## Safety

- Destructive operations (`rename`, `organize`, `duplicates --delete`)
  always print a preview first and require an explicit flag to act.
- Moves/renames never silently overwrite existing files.

## Examples

```powershell
node toolkit.js stats "D:\Photos" -r
node toolkit.js duplicates "D:\Photos" -r          # preview dupes
node toolkit.js duplicates "D:\Photos" -r --delete # clean them up
node toolkit.js rename "D:\Photos\Trip" --pattern "trip_{n}" --apply
node toolkit.js organize "D:\Photos" -r --apply    # sort into YYYY-MM
```
