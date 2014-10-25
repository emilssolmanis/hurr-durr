# 0.2.1
 * README update for new SQLite handler

# 0.2.0
## Breaking
 * Changed storage format to per-date SQLites. Turns out the previous FS one exhausts `inodes` on default installs
 in a couple of months. The old format is still available by specifying `-f file`. There is a conversion script
 used as `hurr-durr-convert-file-to-sqlite --input old_data_dir --output new_data_dir`

## Other
 * Version bump, moved to Tornado 4.x

# 0.1.0
## Breaking
 * Changed directory structure for `FileHandler`, added another layer of nesting with date, so now it's `-d param / YYYYMMDD / thread_id / content`
   instead of the previous `-d param / thread_id / content`.

## Other
 * Updated to new 4chan API
 * Added `-V` / `--version` argument
