
local kpse = kpse or require 'kpse'
local lfs = lfs or require 'lfs'

kpse.set_program_name('lualatex')

function string.startswith(String, Start)
    return string.sub(String,1,string.len(Start)) == Start
end

local graphicspath
local program_name

local function read_files_and_exts()
    -- read all the lines from stdin
    -- first line is file name
    -- second line is list of extensions or empty
    local fileexts = {}
    local in_header = true
    while true do
      local entry = io.read()
      if entry == nil then break end
      if string.startswith(entry, "#graphicspath=") then
          graphicspath = string.sub(entry, 15)
      elseif string.startswith(entry, "#programname=") then
          program_name = string.sub(entry, 14)
      else
          filename = entry
          local extensions = io.read()
          if extensions == nil then break end -- should we warn about a lone filename?
          -- print("found " .. filename .. " " .. extensions)
          fileexts[filename] = extensions
      end
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

-- print("===== GRAPHICS PATH = " .. (graphicspath or ""))
-- print("===== PROGRAM NAME  = " .. (program_name or ""))

local next = next

if next(fileexts) == nil then
    print("No paths read from stdin.")
    os.exit(1)
end

local selfautoparent = kpse.var_value("SELFAUTOPARENT")
-- print(selfautoparent)

-- prepare graphicspath for search
if not graphicspath then
    graphicspath = ""
else
    graphicspath = ":" .. graphicspath
end
for path, exts in pairs(fileexts) do
    -- first test if file as is can be found
    local result
    for gp in string.gmatch(graphicspath, "[^:]*") do
        -- print("searching for " .. gp .. path)
        result = kpse.find_file(gp .. path)
        -- print("found " .. (result or "nothing"))
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
        if result then
            break
        end
    end
    print(path)
    if result then
        print(result)
    else
        print()
    end
end

