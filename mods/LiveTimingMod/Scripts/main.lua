-- ==============================================================================
-- F1 Manager 2024 - Live Timing Mod (UE4SS)
-- High-frequency, thread-safe Live Timing data exporter
-- Exports 20 cars' S1/S2/S3, Lap Times, Tyre, ERS, Fuel, Gaps to live_timing.json
-- ==============================================================================

local UEHelpers = require("UEHelpers")

local OUTPUT_PATH = "ue4ss/Mods/LiveTimingMod/live_timing.json"
local OUTPUT_PATH_TMP = "ue4ss/Mods/LiveTimingMod/live_timing.json.tmp"

local cachedCars = {}
local isInitialized = false
local tickCount = 0
local lastWriteClock = 0.0
local lastCarSearchClock = 0.0
local WRITE_INTERVAL_SEC = 0.50       -- 500ms refresh rate (~2 Hz, balanced performance & responsiveness)
local CAR_SEARCH_COOLDOWN_SEC = 2.5  -- Minimum 2.5s between expensive FindAllOf global object searches
local hookRegistered = false

print("[LiveTimingMod] Loading LiveTimingMod...")

local function SafeGet(obj, prop, default)
    if not obj then return default end
    local ok, val = pcall(function() return obj[prop] end)
    if ok and val ~= nil then return val end
    if obj.GetPropertyValue then
        local ok2, val2 = pcall(function() return obj:GetPropertyValue(prop) end)
        if ok2 and val2 ~= nil then return val2 end
    end
    return default
end

local function SafeNumber(val, default)
    if val == nil then return default or 0 end
    if type(val) == "number" then return val end
    if type(val) == "userdata" and val.GetValue then
        local ok, v = pcall(function() return val:GetValue() end)
        if ok and v then return tonumber(v) or default or 0 end
    end
    local n = tonumber(tostring(val))
    return n or default or 0
end

local function SafeString(val, default)
    if val == nil then return default or "" end
    if type(val) == "string" then return val end
    if type(val) == "userdata" and val.ToString then
        local ok, s = pcall(function() return val:ToString() end)
        if ok and s then return s end
    end
    return tostring(val)
end

-- Escape string for JSON
local function EscapeJsonString(str)
    if not str then return "" end
    local s = tostring(str)
    s = s:gsub('\\', '\\\\')
    s = s:gsub('"', '\\"')
    s = s:gsub('\n', '\\n')
    s = s:gsub('\r', '\\r')
    s = s:gsub('\t', '\\t')
    return s
end

local function TryInitCars()
    cachedCars = {}
    local allCars = nil
    
    local ok, res = pcall(function() return FindAllOf("CarActor") end)
    if ok and res and #res > 0 then
        allCars = res
    else
        local ok2, res2 = pcall(function() return FindAllOf("BP_BaseCar2022_Actor_C") end)
        if ok2 and res2 and #res2 > 0 then
            allCars = res2
        end
    end

    if allCars and #allCars > 0 then
        for _, car in pairs(allCars) do
            local isValid = false
            pcall(function() isValid = car and car:IsValid() end)
            if isValid then
                local isSC = false
                pcall(function()
                    if car.IsSafetyCar and car:IsSafetyCar() then
                        isSC = true
                    end
                end)
                if not isSC then
                    table.insert(cachedCars, car)
                end
            end
        end

        if #cachedCars >= 18 then
            isInitialized = true
            print(string.format("[LiveTimingMod] Ready: tracked %d racing cars", #cachedCars))
        else
            isInitialized = false
        end
    else
        isInitialized = false
    end
end

local function FormatCarEntry(car, index)
    local carData = SafeGet(car, "CarData", nil)
    if not carData then
        return nil
    end

    local simId = SafeNumber(SafeGet(car, "SimCarID", index - 1), index - 1)
    local driverName = EscapeJsonString(SafeString(SafeGet(carData, "DriverName", "")))
    local driverCode = EscapeJsonString(SafeString(SafeGet(carData, "DriverCode", "")))
    local driverNumber = SafeNumber(SafeGet(carData, "DriverNumber", 0))
    local teamName = EscapeJsonString(SafeString(SafeGet(carData, "TeamName", "")))

    local pos = SafeNumber(SafeGet(carData, "RacePos", index))
    local lapCount = SafeNumber(SafeGet(carData, "LapCount", 0))
    local lapProgress = SafeNumber(SafeGet(carData, "LapProgress", 0.0))
    local curLapTime = SafeNumber(SafeGet(carData, "CurrentLapTime", 0.0))
    local lastLapTime = SafeNumber(SafeGet(carData, "LastLapTime", 0.0))
    local bestLap = SafeNumber(SafeGet(carData, "BestLap", 0.0))
    local deltaLead = SafeNumber(SafeGet(carData, "CarTimeDeltaFromLead", 0.0))

    local s1Time = SafeNumber(SafeGet(carData, "Sector1Time", 0.0))
    local s1State = SafeNumber(SafeGet(carData, "Sector1State", 0))
    local s2Time = SafeNumber(SafeGet(carData, "Sector2Time", 0.0))
    local s2State = SafeNumber(SafeGet(carData, "Sector2State", 0))
    local s3Time = SafeNumber(SafeGet(carData, "Sector3Time", 0.0))
    local s3State = SafeNumber(SafeGet(carData, "Sector3State", 0))

    local tyreCompound = SafeNumber(SafeGet(carData, "TyreCompound", 0))
    local tyreType = SafeNumber(SafeGet(carData, "TyreType", -1), -1)
    -- If dry compound is 0/unset, check TyreType (in ETyreType: 6 = Inter, 7 = Wet)
    if tyreCompound == 0 and tyreType >= 0 then
        if tyreType == 6 then
            tyreCompound = 4 -- Inter
        elseif tyreType == 7 then
            tyreCompound = 5 -- Wet
        end
    end
    local tyreWear = SafeNumber(SafeGet(carData, "TyreWearPercentage", 0))
    local tyreTemp = SafeNumber(SafeGet(carData, "TyreTemperature", 0))
    local ersCharge = SafeNumber(SafeGet(carData, "ERSBatteryChargePercentage", 0))
    local drsState = SafeNumber(SafeGet(carData, "DRSState", 0))
    local fuel = SafeNumber(SafeGet(carData, "Fuel", 0.0))
    local speedKph = SafeNumber(SafeGet(carData, "SpeedKPH", 0))
    local gear = SafeNumber(SafeGet(carData, "Gear", 0))

    local pitStart = SafeNumber(SafeGet(carData, "PitStopStartTime", 0.0))
    local pitEnd = SafeNumber(SafeGet(carData, "PitStopEndTime", 0.0))
    local inPit = (pitStart > 0.0 and pitEnd <= 0.0)

    local completeState = SafeNumber(SafeGet(carData, "RaceCompleteState", 0))

    return string.format(
        [[{"car_index":%d,"driver_name":"%s","driver_code":"%s","driver_number":%d,"team_name":"%s","position":%d,"lap_count":%d,"lap_progress":%.4f,"current_lap_time":%.3f,"last_lap_time":%.3f,"best_lap_time":%.3f,"gap_to_leader":%.3f,"s1_time":%.3f,"s1_state":%d,"s2_time":%.3f,"s2_state":%d,"s3_time":%.3f,"s3_state":%d,"tyre_compound":%d,"tyre_type":%d,"tyre_wear":%d,"tyre_temp":%d,"ers_charge":%d,"drs_state":%d,"fuel":%.2f,"speed_kph":%d,"gear":%d,"is_in_pit":%s,"race_complete_state":%d}]],
        simId, driverName, driverCode, driverNumber, teamName,
        pos, lapCount, lapProgress, curLapTime, lastLapTime,
        bestLap, deltaLead,
        s1Time, s1State, s2Time, s2State, s3Time, s3State,
        tyreCompound, tyreType, tyreWear, tyreTemp, ersCharge, drsState,
        fuel, speedKph, gear, inPit and "true" or "false", completeState
    )
end

local function ExportLiveTiming()
    local carEntries = {}

    for i, car in ipairs(cachedCars) do
        local isValid = false
        pcall(function() isValid = car and car:IsValid() end)
        if not isValid then
            -- Level change or invalid car reference, reset
            print("[LiveTimingMod] Car actor invalidated, resetting car cache...")
            isInitialized = false
            cachedCars = {}
            lastCarSearchClock = os.clock()
            return
        end

        local ok, entry = pcall(FormatCarEntry, car, i)
        if ok and entry then
            table.insert(carEntries, entry)
        end
    end

    if #carEntries == 0 then return end

    local nowClock = os.clock()
    local jsonStr = string.format(
        [[{"timestamp":%.3f,"session_type":"Race","car_count":%d,"cars":[%s]}]] .. "\n",
        nowClock, #carEntries, table.concat(carEntries, ",")
    )

    -- Write directly in place to avoid Windows file deletion / rename lock races
    local f = io.open(OUTPUT_PATH, "w")
    if f then
        f:write(jsonStr)
        f:close()
    else
        -- Fallback via tmp write if direct open encountered transient handle lock
        local fTmp = io.open(OUTPUT_PATH_TMP, "w")
        if fTmp then
            fTmp:write(jsonStr)
            fTmp:close()
            pcall(function()
                os.remove(OUTPUT_PATH)
                os.rename(OUTPUT_PATH_TMP, OUTPUT_PATH)
            end)
        end
    end
end

local function OnTick()
    tickCount = tickCount + 1

    -- Cooldown-protected car scan if not yet initialized
    -- (prevents expensive FindAllOf UObject traversal from being triggered 20 times/sec)
    if not isInitialized then
        local nowClock = os.clock()
        if nowClock - lastCarSearchClock >= CAR_SEARCH_COOLDOWN_SEC then
            lastCarSearchClock = nowClock
            pcall(TryInitCars)
        end
        return
    end

    -- Throttle file writing (synchronous I/O throttled to WRITE_INTERVAL_SEC)
    local nowClock = os.clock()
    if nowClock - lastWriteClock >= WRITE_INTERVAL_SEC then
        lastWriteClock = nowClock
        pcall(ExportLiveTiming)
    end
end

local function RegisterHooks()
    local ok1 = pcall(function()
        RegisterHook("/Game/Cars/BaseCars/BaseCar2022/BP_BaseCar2022_Actor.BP_BaseCar2022_Actor_C:ReceiveTick", OnTick)
        print("[LiveTimingMod] Hooked BP_BaseCar2022_Actor_C:ReceiveTick successfully")
    end)

    pcall(function()
        RegisterHook("/Script/RaceSim.CarEventManagerComponent:OnRaceSimEventReceived", function(self, i_event)
            -- Checkpoint event hook: retry initialization if cars not ready.
            -- NOTE: Do NOT synchronously write file here to prevent massive I/O lag storms at 4x/8x/16x game speeds.
            if not isInitialized then
                local nowClock = os.clock()
                if nowClock - lastCarSearchClock >= CAR_SEARCH_COOLDOWN_SEC then
                    lastCarSearchClock = nowClock
                    pcall(TryInitCars)
                end
            end
        end)
    end)

    return ok1
end

local function TryRegisterHooks()
    if hookRegistered then return end
    if RegisterHooks() then
        hookRegistered = true
        print("[LiveTimingMod] All hooks registered")
    else
        ExecuteWithDelay(3000, TryRegisterHooks)
    end
end

ExecuteWithDelay(2000, TryRegisterHooks)
print("[LiveTimingMod] LiveTimingMod initialized")
