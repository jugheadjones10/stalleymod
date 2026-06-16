using System;
using StardewModdingAPI;
using StardewValley;
using Microsoft.Xna.Framework;
using StardewValley.Menus;
using System.Text;
using System.Threading.Tasks;
using StardewModdingAPI.Events;
using StardewValley.Buildings;
using Newtonsoft.Json;
using StardewValley.TerrainFeatures;
using xTile.Dimensions;
using StardewValley.Objects;
using static ActionSpace.actions.Actions;
using System.IO;
using StardewValley.Objects;

namespace ActionSpace.actions
{
	public static class ActionsAPI
	{
        private static void LogToFile(string message, Mod mod)
        {
            try
            {
                string logFilePath = Path.Combine(mod.Helper.DirectoryPath, observeSpaceTest.ModEntry.LogFileName);
                string logMessage = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} - {message}";
                File.AppendAllText(logFilePath, logMessage + Environment.NewLine);
            }
            catch (Exception ex)
            {
                mod.Monitor.Log($"Failed to write log: {ex.Message}", LogLevel.Error);
            }
        }

        public static async Task<bool> move(string x, string y, Mod mod)
        {
            if (Game1.activeClickableMenu is not null){
                return false;
            }

            var taskCompletionSource = new TaskCompletionSource<bool>();
            int xI = int.Parse(x);
            int yI = int.Parse(y);

            LogToFile($"starting moving to x:{xI}, y:{yI}", mod);
            void OnWarped(object? sender, WarpedEventArgs e)
            {
                LogToFile($"moving terminated by warp x:{xI}, y:{yI}", mod);
                taskCompletionSource.TrySetResult(true);
                mod.Helper.Events.Player.Warped -= OnWarped;
            }
            mod.Helper.Events.Player.Warped += OnWarped;
            Action<MoveResult> onComplete = (result) => {
                LogToFile($"moving terminated by complete x:{xI}, y:{yI}", mod);
                mod.Helper.Events.Player.Warped -= OnWarped;
                taskCompletionSource.TrySetResult(result.Success);
            };
            Actions.StartAutoPathing(new Vector2(xI, yI), onComplete, mod);
            LogToFile($"awaiting moving x:{xI}, y:{yI}", mod);

            bool success = await taskCompletionSource.Task;
            LogToFile($"moving completed, status = {success}, x:{xI}, y:{yI}", mod);

            return success;
        }

        // Returns "true" on success, or "false%reason[:blocker]" on failure
        // (e.g. "false%target_impassable:Stone", "false%unreachable", "false%npc_blocked",
        // "false%menu_open", "false%warped:<NewLocation>").
        // The Python ActionProxy.move parses this into (success, reason).
        public static async Task<string> move_relative(string x, string y, Mod mod)
        {
            // A move is a no-op while a menu/dialog is up (the game freezes player movement), so
            // auto-pathing would never complete and this would hang until the socket times out.
            // Bail immediately with a reason the program can act on instead.
            if (Game1.activeClickableMenu is not null)
            {
                return "false%menu_open";
            }

            // Phase timing for perf debugging. move_relative is the dominant exec_ms cost, so split
            // it into setup (parse), pathfind (StartAutoPathing = A* PathFindController build), traverse
            // (the awaited tile-by-tile walk), and postcheck (warp-tile check). One PERF_MOVE line per
            // call; dist is the manhattan distance, which traverse scales with.
            var moveSw = System.Diagnostics.Stopwatch.StartNew();

            var taskCompletionSource = new TaskCompletionSource<MoveResult>();
            int xRelative = int.Parse(x);
            int yRelative = int.Parse(y);
            int xOrigin = Game1.player.TilePoint.X;
            int yOrigin = Game1.player.TilePoint.Y;
            int xI = xOrigin + xRelative;
            int yI = yOrigin + yRelative;

            LogToFile($"starting moving to x:{xI}, y:{yI} (relative {xRelative}, {yRelative})", mod);
            void OnWarped(object? sender, WarpedEventArgs e)
            {
                // Pathing crossed a warp tile (e.g. a door): the player teleported to another map
                // and did NOT reach the requested tile. Report failure so the program re-observes
                // instead of blindly continuing with relative moves on the wrong map.
                string newLocation = e.NewLocation?.Name ?? "unknown";
                LogToFile($"moving terminated by warp to {newLocation} x:{xI}, y:{yI}", mod);
                taskCompletionSource.TrySetResult(new MoveResult(false, $"warped:{newLocation}"));
                mod.Helper.Events.Player.Warped -= OnWarped;
            }
            mod.Helper.Events.Player.Warped += OnWarped;
            Action<MoveResult> onComplete = (result) => {
                LogToFile($"moving terminated by complete, status = {result.Success}, x:{xI}, y:{yI}", mod);
                mod.Helper.Events.Player.Warped -= OnWarped;
                taskCompletionSource.TrySetResult(result);
            };
            long setupMs = moveSw.ElapsedMilliseconds;

            moveSw.Restart();
            Actions.StartAutoPathing(new Vector2(xI, yI), onComplete, mod);
            long pathfindMs = moveSw.ElapsedMilliseconds;
            LogToFile($"awaiting moving x:{xI}, y:{yI}", mod);

            moveSw.Restart();
            MoveResult result = await taskCompletionSource.Task;
            long traverseMs = moveSw.ElapsedMilliseconds;
            mod.Helper.Events.Player.Warped -= OnWarped;

            // A path whose ENDPOINT is a warp tile (e.g. a building door) reaches the tile and
            // reports success a tick BEFORE the warp actually fires, so OnWarped above misses it
            // and we'd return "true" while the map is about to change under us. Detect that case
            // explicitly: if we finished standing on a registered warp tile, report it as a warp
            // so the caller re-observes instead of continuing with stale (now wrong-map) relative
            // coordinates. Warps crossed mid-path are still handled by OnWarped above.
            moveSw.Restart();
            string ret;
            if (result.Success)
            {
                var p = Game1.player.TilePoint;
                var warp = Game1.currentLocation.warps.ToList()
                    .FirstOrDefault(w => w.X == p.X && w.Y == p.Y);
                if (warp != null)
                {
                    LogToFile($"move ended on warp tile x:{xI}, y:{yI} -> warped:{warp.TargetName}", mod);
                    ret = $"false%warped:{warp.TargetName}";
                }
                else
                {
                    ret = "true";
                }
            }
            else
            {
                ret = $"false%{result.Reason}";
            }
            long postcheckMs = moveSw.ElapsedMilliseconds;

            int dist = Math.Abs(xRelative) + Math.Abs(yRelative);
            LogToFile($"PERF_MOVE,{DateTime.Now:HH:mm:ss.fff},dist={dist},setup_ms={setupMs},pathfind_ms={pathfindMs},traverse_ms={traverseMs},postcheck_ms={postcheckMs}", mod);
            LogToFile($"moving completed, status = {result.Success}, reason = {result.Reason}, x:{xI}, y:{yI}", mod);
            return ret;
        }

        public static async Task<bool> move_step(string direction, Mod mod)
        {
            if (Game1.activeClickableMenu is not null)
            {
                return false;
            }
            var status = await Actions.move(direction, mod);
            return status;
        }

        public static void use(Mod mod)
        {
            //Actions.use(mod);
            if (Game1.activeClickableMenu is not null)
            {
                return;
            }
            Actions.useWithAnim(mod);
        }

        public static void turn(string direction, Mod mod)
        {
            if (Game1.activeClickableMenu is not null)
            {
                return;
            }
            Actions.turn(int.Parse(direction), mod);
        }

        public static void interact(Mod mod)
        {
            if (Game1.activeClickableMenu is not null)
            {
                return;
            }
            Actions.interact(mod);
        }

        public static void craft(string item, Mod mod)
        {
            if (Game1.activeClickableMenu is not null)
            {
                return;
            }
            Actions.craft(item, mod);
        }

        public static void choose_option(string index, string quality, string direction, Mod mod)
        {
            int indexI = int.Parse(index);
            int qualityI = int.Parse(quality);
            int directionI = int.Parse(direction);
            if (indexI <= 0)
            {
                Actions.exit_menu();
            }
            else
            {
                indexI = indexI - 1;
            }
            if (Game1.activeClickableMenu is ShopMenu)
            {
                if (directionI == 0)
                {
                    Actions.buy_from_shop(indexI, qualityI, mod);
                }
                else
                {
                    Actions.sell_to_shop_by_index(indexI, mod);
                }
            }
            else if (Game1.activeClickableMenu is DialogueBox)
            {
                Actions.select_dialogue(indexI, mod);
            }
            else if (Game1.activeClickableMenu is ItemGrabMenu)
            {
                if (directionI == 0)
                {
                    take_from_chest(index, quality, mod);
                }
                else
                {
                    put_to_chest(index, quality, mod);
                }
            }
            else
            {
                Actions.exit_menu();
            }
        }

        public static void take_from_chest(string index, string quantity, Mod mod)
        {
            var menu = Game1.activeClickableMenu;
            if (menu is ItemGrabMenu itemGrabMenu)
            {
                if (itemGrabMenu.context is Chest chest)
                {
                    var indexI = int.Parse(index);
                    var quantityI = int.Parse(quantity);
                    Helper.ChestHelper.TakeXItemsFromChest(chest, indexI, quantityI);
                }
            }
        }

        public static void put_to_chest(string index, string quantity, Mod mod)
        {
            var menu = Game1.activeClickableMenu;
            if (menu is ItemGrabMenu itemGrabMenu)
            {
                if (itemGrabMenu.context is Chest chest)
                {
                    var indexI = int.Parse(index);
                    var quantityI = int.Parse(quantity);
                    Helper.ChestHelper.PutXItemsIntoChest(chest, indexI, quantityI);
                }
            }
        }

        public static void sell_current_item(Mod mod)
        {
            Actions.sell_to_shop(mod);
        }

        public static void choose_item(string index, Mod mod)
        {
            int indexI = int.Parse(index);
            if (indexI >= 0 && indexI < Game1.player.MaxItems)
            {
                var item = Game1.player.Items[indexI];
                Game1.player.CurrentToolIndex = indexI;
            }
        }

        public static void attach(string index, Mod mod)
        {
            int indexI = int.Parse(index);
            if (indexI >= 0 && indexI < Game1.player.MaxItems)
            {
                var item = Game1.player.Items[indexI];
                if (item is StardewValley.Object obj)
                {
                    Actions.attach(obj, mod);
                }
            }
        }

        public static void detach(Mod mod)
        {
            Actions.detach(mod);
        }

        public static string observe_v2(string sizeS, Mod mod)
        {
            var size = int.Parse(sizeS);
            var data = Actions.ExportGameData_v2(size, mod);
            mod.Monitor.Log("data received");
            return data;
        }

        public static string observe_v2_light(string sizeS, Mod mod)
        {
            var size = int.Parse(sizeS);
            // Same data as observe_v2 but without the screenshot payload, so we avoid
            // serializing / transferring ~11 MB of base64 per call.
            var data = Actions.ExportGameData_v2(size, mod, includeScreenshot: false);
            mod.Monitor.Log("light data received");
            return data;
        }

        public static byte[]? observe(string sizeS, Mod mod)
        {
            var size = int.Parse(sizeS);
            var data = Actions.ExportGameData(size, mod);
            mod.Monitor.Log("data received");
            return data;
        }

        public static void exit_menu(Mod mod)
        {
            Actions.exit_menu();
        }

        // Press "OK" on the end-of-day LevelUpMenu, choosing a profession on profession
        // levels (skill 5 & 10). `choiceS` is the 1-based profession index the agent picks
        // (matching current_menu.responses[].responseKey); 0 means "no explicit choice".
        // Returns:
        //   "true"                       -> level confirmed (perk applied; menu closing)
        //   "false%no_level_up_menu"     -> no LevelUpMenu is currently open
        //   "false%level_up_not_ready"   -> menu open but still animating in / not populated
        // Once we flip isActive=false the menu's own update() calls exitThisMenu() and the
        // end-of-night menu stack advances on its own.
        public static string confirm_level_up(string choiceS, Mod mod)
        {
            int choice = int.TryParse(choiceS, out var c) ? c : 0;

            if (Game1.activeClickableMenu is not LevelUpMenu menu)
            {
                return "false%no_level_up_menu";
            }
            if (!menu.isActive || !menu.informationUp)
            {
                return "false%level_up_not_ready";
            }

            if (menu.isProfessionChooser)
            {
                // Profession levels (5 & 10) force a left/right choice; okButtonClicked()
                // would silently drop the profession. professionsToChoose is private and is
                // populated on the menu's first update() tick (gated by hasUpdatedProfessions).
                if (!menu.hasUpdatedProfessions)
                {
                    return "false%level_up_not_ready";
                }

                var field = typeof(LevelUpMenu).GetField("professionsToChoose",
                    System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                var professions = field?.GetValue(menu) as System.Collections.Generic.List<int>;
                if (professions == null || professions.Count == 0)
                {
                    return "false%level_up_not_ready";
                }

                // Map the 1-based agent choice onto professionsToChoose. Fall back to the
                // first option when no valid choice is given so a run never stalls; the agent
                // is expected to read current_menu.responses and pass an explicit choice.
                int index = (choice >= 1 && choice <= professions.Count) ? choice - 1 : 0;
                int chosen = professions[index];
                if (!Game1.player.professions.Contains(chosen))
                {
                    Game1.player.professions.Add(chosen);
                }
                menu.getImmediateProfessionPerk(chosen);
                menu.isProfessionChooser = false;
                menu.RemoveLevelFromLevelList();
                menu.isActive = false;
                menu.informationUp = false;
                mod.Monitor.Log($"confirm_level_up: selected profession {chosen} (choice {choice})", LogLevel.Info);
            }
            else
            {
                menu.okButtonClicked();
                mod.Monitor.Log("confirm_level_up: pressed OK", LogLevel.Info);
            }
            return "true";
        }

        public async static Task<bool> wait_game_start(Mod mod)
        {
            var taskCompletionSource = new TaskCompletionSource<bool>();
            Action onComplete = () => taskCompletionSource.TrySetResult(true);
            EventHandler<DayStartedEventArgs>? dayStarted = null;
            EventHandler<UpdateTickedEventArgs>? counterUpdate = null;
            var count = 0;
            counterUpdate = (object? sender, UpdateTickedEventArgs e) =>
            {
                if (count < 100)
                {
                    count += 1;
                    return;
                }
                else
                {
                    mod.Helper.Events.GameLoop.UpdateTicked -= counterUpdate;
                    onComplete();
                }
            };
            dayStarted = (object? sender, DayStartedEventArgs e) =>
            {
                mod.Helper.Events.GameLoop.DayStarted -= dayStarted;
                mod.Helper.Events.GameLoop.UpdateTicked += counterUpdate;
            };
            mod.Helper.Events.GameLoop.DayStarted += dayStarted;
            await taskCompletionSource.Task;
            return true;
        }

        public async static Task<bool> enter_load_menu(Mod mod)
        {
            var taskCompletionSource = new TaskCompletionSource<bool>();
            Action onComplete = () => taskCompletionSource.SetResult(true);
            testUtils.TestUtils.enterLoadGameMenu(mod, onComplete);
            await taskCompletionSource.Task;
            return true;
        }

        public async static Task<bool> load_game_record(string record_name, Mod mod)
        {
            mod.Monitor.Log($"Try loading game: {record_name}");
            Actions.clearDayStartRecords();
            try
            {
                SaveGame.Load(record_name);
                IClickableMenu activeClickableMenu = Game1.activeClickableMenu;
                TitleMenu val;
                if ((val = (TitleMenu)(object)((activeClickableMenu is TitleMenu) ? activeClickableMenu : null)) != null)
                {
                    ((IClickableMenu)val).exitThisMenu(false);
                }
            }
            catch (Exception ex)
            {
                mod.Monitor.Log(ex.Message);
            }
            mod.Monitor.Log($"Successfully loaded game: {record_name}");
            return true;
        }


        public async static Task<bool> load_game(string which, Mod mod)
        {
            var taskCompletionSource = new TaskCompletionSource<bool>();
            Action onComplete = () => taskCompletionSource.SetResult(true);
            mod.Monitor.Log($"Try loading game: {which}");
            LogToFile($"loading game: {which}", mod);
            try
            {
                testUtils.TestUtils.loadGame(which, mod, onComplete);
            }
            catch (Exception ex)
            {
                mod.Monitor.Log(ex.Message);
            }
            mod.Monitor.Log($"Successfully loaded game: {which}");
            LogToFile($"Successfully loaded game: {which}", mod);

            await taskCompletionSource.Task;
            return true;
        }

        public static void exit_title(Mod mod)
        {
            testUtils.TestUtils.exitGameToTitle();
        }

        public static void open_map(Mod mod)
        {
            Game1.activeClickableMenu = new GameMenu();
            if (Game1.activeClickableMenu is GameMenu newMenu)
            {
                newMenu.currentTab = 3;
            }
        }

        public static async Task<bool> navigate(string name, Mod mod)
        {
            foreach (Warp warp in Game1.currentLocation.warps.ToList())
            {
                if (name == warp.TargetName)
                {
                    var res = await move(warp.X.ToString(), warp.Y.ToString(), mod);
                    if (res)
                    {
                        return true;
                    }
                    else
                    {
                        continue;
                    }
                }
            }
            return false;
        }

        public static void pause(Mod mod)
        {
            Game1.paused = true;
        }

        public static void resume(Mod mod)
        {
            Game1.paused = false;
        }

        public static string get_surroundings(string sizeS, Mod mod)
        {
            int size = int.Parse(sizeS);
            var playPoint = Game1.player.TilePoint;
            int xI = playPoint.X;
            int yI = playPoint.Y;

            var layer = Game1.player.currentLocation.Map.GetLayer("Back");

            int mapWidth = layer.LayerWidth;
            int mapHeight = layer.LayerHeight;
            int minX = Math.Max(0, xI - size);
            int maxX = Math.Min(mapWidth - 1, xI + size);
            int minY = Math.Max(0, yI - size);
            int maxY = Math.Min(mapHeight - 1, yI + size);

            var tileInfoList = new List<string>();

           
            for (int tileX = minX; tileX <= maxX; tileX++)
            {
                for (int tileY = minY; tileY <= maxY; tileY++)
                {
                    
                    string infoJson = get_tile_info(tileX.ToString(), tileY.ToString(), mod);
                    tileInfoList.Add(infoJson);
                }
            }
            var settings = new JsonSerializerSettings
            {
                ReferenceLoopHandling = ReferenceLoopHandling.Ignore,
                Formatting = Formatting.Indented
            };
            var j_info = JsonConvert.SerializeObject(tileInfoList, settings);
            return j_info;
        }

        public static string get_tile_info(string x, string y, Mod mod)
        {
            int xI = int.Parse(x);
            int yI = int.Parse(y);
            var key = new Vector2(xI, yI);
            object object_info = "";
            object terrain_info = "";
            object builing_info = "";
            object crop_info = "";
            object? debris_info = "";
            object? furniture_info = "";
            if (Game1.currentLocation.objects.ContainsKey(key))
            {
                object_info = Game1.currentLocation.objects[key].BaseName;
            }
            if (Game1.currentLocation.terrainFeatures.ContainsKey(key)){
                terrain_info = Game1.currentLocation.terrainFeatures[key].GetType().ToString();
            }
            if (Game1.currentLocation.buildings is not null)
            {
                foreach (Building building in Game1.currentLocation.buildings)
                {
                    var box = building.GetBoundingBox();
                    var tileSize = Game1.tileSize;
                    var xP = xI * tileSize;
                    var yP = yI * tileSize;
                    if (box.Contains(new Point(xP, yP)))
                    {
                        builing_info = building.buildingType.Value;
                    }
                }
            }
            foreach (Debris debris in Game1.currentLocation.debris.ToList())
            {
                foreach (Chunk chunk in debris.Chunks.ToList())
                {
                    int chunkTileX = (int)(chunk.position.X / Game1.tileSize);
                    int chunkTileY = (int)(chunk.position.Y / Game1.tileSize);
                    
                    if (chunkTileX == xI && chunkTileY == yI)
                    {
                        debris_info = debris?.item?.BaseName;
                        if (debris_info is null)
                        {
                            debris_info = debris?.itemId?.Value;
                        }
                    }
                }
            }
            if (Game1.currentLocation is Farm farm)
            {
                if (farm.GetMainMailboxPosition().X == xI && farm.GetMainMailboxPosition().Y == yI)
                {
                    builing_info = "mailbox";
                }
            }
            if (Game1.currentLocation.terrainFeatures.TryGetValue(key, out var value) && value is HoeDirt hoeDirt && hoeDirt.crop != null)
            {
                var crop = hoeDirt.crop;
                crop_info = new
                {
                    seed_id = crop.netSeedIndex.Value,
                    is_dead = crop.dead.Value,
                    forage_crop = crop.forageCrop.Value,
                    fully_grown = crop.fullyGrown.Value,
                    current_phase = crop.currentPhase.Value,
                    index_harvest = crop.indexOfHarvest.Value
                };
            }
            var position = new List<int>();
            position.Add(xI);
            position.Add(yI);

            if (Game1.currentLocation.furniture is not null)
            {
                var furnitureList = Game1.currentLocation.furniture.ToList();
                foreach (var furnitureItem in furnitureList)
                {
                    if (furnitureItem.GetBoundingBox().Contains(new Point(position[0] * Game1.tileSize, position[1] * Game1.tileSize)))
                    {
                        furniture_info = furnitureItem.BaseName;
                    }
                }
            }

            var tile_info = new
            {
                position = position,
                object_at_tile = object_info,
                terrain_at_tile = terrain_info,
                building_info = builing_info,
                crop_at_tile = crop_info,
                debris_at_tile = debris_info,
                furniture_at_tile = furniture_info,
                placeable = Game1.currentLocation.isTilePlaceable(key)
            };
            var settings = new JsonSerializerSettings
            {
                ReferenceLoopHandling = ReferenceLoopHandling.Ignore,
                Formatting = Formatting.Indented
            };
            var j_info = JsonConvert.SerializeObject(tile_info, settings);
            return j_info;
        }

    }
}

