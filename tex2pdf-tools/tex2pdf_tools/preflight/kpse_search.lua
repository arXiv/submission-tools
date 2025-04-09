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
-- Output comes again in three line units. The first two lines are the same as
-- the two lines of the input, the third line lists the found file, or
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

function string.startswith(String, Start)
    return string.sub(String,1,string.len(Start)) == Start
end

local graphicspath
local program_name
local mark_sys_files = true
local subdir
local debug = 0

local function _do_debug(s,n)
    if n <= debug then
        print("DEBUG: " .. s)
    end
end
local function _debug(s)
    _do_debug(s,1)
end
local function _ddebug(s)
    _do_debug(s,2)
end


local function read_files_and_exts()
    -- read all the lines from stdin
    -- first line is file name
    -- second line is list of extensions or empty
    local fileexts = {}
    local in_header = true
    while true do
      local entry = io.read()
      if entry == nil then break end
      if string.startswith(entry, "#graphicspath=") and in_header then
          graphicspath = string.sub(entry, 15)
      elseif string.startswith(entry, "#programname=") and in_header then
          program_name = string.sub(entry, 14)
      else
          in_header = false
          filename = entry
          local extensions = io.read()
          if extensions == nil then break end -- should we warn about a lone filename?
          _ddebug("found " .. filename .. " " .. extensions)
          if fileexts[filename] == nil then
              fileexts[filename] = {}
          end
          fileexts[filename][extensions] = 1
      end
    end
    return fileexts
end


local cur_arg = 1
while cur_arg <= #arg do
    if arg[cur_arg] == "-mark-sys-files" then
        mark_sys_files = false
    elseif arg[cur_arg] == "-v" then
        debug = 1
    elseif arg[cur_arg] == "-vv" then
        debug = 2
    else
        subdir = arg[cur_arg]
    end
    cur_arg = cur_arg + 1
end

if subdir then
    lfs.chdir(subdir)
end

local fileexts = read_files_and_exts()

_debug("===== GRAPHICS PATH = " .. (graphicspath or ""))
_debug("===== PROGRAM NAME  = " .. (program_name or ""))

-- use the configured or default program name
kpse.set_program_name(program_name or 'lualatex')

local next = next

if next(fileexts) == nil then
    print("No paths read from stdin.")
    os.exit(1)
end

local selfautoparent = kpse.var_value("SELFAUTOPARENT")
_debug("selfautoparent = " .. selfautoparent)

-- prepare graphicspath for search
if not graphicspath then
    graphicspath = ""
else
    graphicspath = ":" .. graphicspath
end


-- search for all files with possible extensions given
-- in addition, search also in entries of graphicspath
for path, subv in pairs(fileexts) do
    _ddebug("path = " .. path)
    for exts, val in pairs(subv) do
        local result
        local saved_exts
        _ddebug("Entering search for " .. path)
        saved_exts = exts
        _ddebug("exts = " .. exts)
        _ddebug("val = " .. val)
        -- loop over the graphicspath entries. We have at least one
        -- empty match to search as is
        for gp in string.gmatch(graphicspath, "[^:]*") do
            _ddebug("Entering gp search for " .. gp .. path)
            -- if we have an extension, search for the file as is first
            if path:match("^.+(%..+)$") then
                _debug("Found an extension")
                -- Note that graphicspath entries need a final /
                result = kpse.find_file(gp .. path)
                if result then
                    _ddebug("Found it! A")
                    goto end_of_loops
                end
            end
            -- print("found " .. (result or "nothing"))
            -- if we don't have a result, that is:
            -- * either file didn't have an extension to begin with
            -- * or we didn't find anything as is
            -- then search for the file with extension
            if not result then
                for ext in string.gmatch(exts, "[^%s]+") do
                    _ddebug("searching for " .. gp .. path .. "." .. ext)
                    result = kpse.find_file(gp .. path .. "." .. ext)
                    if result then
                        _ddebug("Found it! B")
                        goto end_of_loops
                    end
                end
            end
        end
        ::end_of_loops::
        if result and not mark_sys_files then
            if string.startswith(result, selfautoparent) then
                result = "SYSTEM:" .. result
            end
        end
        print(path)
        print(saved_exts)
        if result then
            print(result)
        else
            print()
        end
    end
end

