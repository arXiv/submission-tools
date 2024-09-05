
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
      -- print("found " .. filename .. " " .. extensions)
      fileexts[filename] = extensions
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

for path, exts in pairs(fileexts) do
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
        print(result)
    else
        print()
    end
end

