--
-- kpse_search.lua
--
-- Public domain.
--
-- Usage:
--   texlua kpse_search.lua [-mark-sys-files] <directory>
--
-- Change into the given directory, then read file names and extensions
-- from stding and try to resolve them via kpse, reporting the findings.
--
-- Input format:
-- Input comes in two line units. The first line contains the filename
-- to look up. It *can* have an extension, but does not need to have.
-- The second line contains a list of extensions to be tested in case
-- the <filename> itself cannot be found using kpse
--
--   filename
--   ext1 ...
--   ...
--
-- Output format:
-- Output comes again in two line units. The first line is the same as
-- the first line of the input, the second line lists the found file, or
-- is empty if not found.
--
-- The option -mark-sys-files can be used to prefix found files with
--   SYSTEM:
-- if they come from the respective TeX installation, and not from the
-- input directory.
--
-- TODO:
-- - make set_program_name configurable

local kpse = kpse or require 'kpse'
local lfs = lfs or require 'lfs'

kpse.set_program_name('lualatex')

function string.startswith(String, Start)
    return string.sub(String,1,string.len(Start)) == Start
end

local function read_files_and_exts()
    -- read all the lines from stdin
    -- first line is file name
    -- second line is list of extensions or empty
    local fileexts = {}
    while true do
      local filename = io.read()
      if filename == nil then break end
      local extensions = io.read()
      if extensions == nil then break end -- should we warn about a lone filename?
      if fileexts[filename] == nil then
        fileexts[filename] = {}
      end
      -- print("found " .. filename .. " " .. extensions)
      fileexts[filename][extensions] = 1
    end
    return fileexts
end

local mark_sys_files = true
local subdir
if arg[1] == "-mark-sys-files" then
    mark_sys_files = false
    subdir = arg[2]
else
    subdir = arg[1]
end

if subdir then
    lfs.chdir(subdir)
end

local fileexts = read_files_and_exts()

local next = next

if next(fileexts) == nil then
    print("No paths read from stdin.")
    os.exit(1)
end

local selfautoparent = kpse.var_value("SELFAUTOPARENT")
-- print(selfautoparent)

for path, exts_table in pairs(fileexts) do
  for exts, val in pairs(exts_table) do
    -- first test if file as is can be found
    local result = kpse.find_file(path)
    if not result then
        for ext in string.gmatch(exts, "[^%s]+") do
            result = kpse.find_file(path .. "." .. ext)
            if result then
                break
            end
        end
    end
    if result and not mark_sys_files then
        if string.startswith(result, selfautoparent) then
            result = "SYSTEM:" .. result
        end
    end
    print(path)
    if result then
        print(exts .. ":" .. result)
    else
        print(exts .. ":")
    end
  end
end

