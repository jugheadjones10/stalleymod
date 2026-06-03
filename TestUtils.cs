using System;
using System.Collections.Generic;
using System.Reflection;
using Microsoft.Xna.Framework;
using Netcode;
using StardewModdingAPI;
using StardewModdingAPI.Events;
using StardewValley;
using StardewValley.Inventories;
using StardewValley.Locations;
using StardewValley.Menus;
using StardewValley.Objects;
using StardewValley.Tools;

namespace testUtils;

public static class TestUtils
{
	private static string TEST_UTILS_LOG = "Test Utils Log:";

	public static readonly Dictionary<string, int> ItemIdMap = new Dictionary<string, int>
	{
		{ "copperBar", 334 },
		{ "ironBar", 335 },
		{ "goldBar", 336 },
		{ "iridiumBar", 337 },
		{ "wood", 388 },
		{ "stone", 390 },
		{ "copper", 378 },
		{ "iron", 380 },
		{ "coal", 382 },
		{ "gold", 384 },
		{ "iridium", 386 },
		{ "stardrop", 434 }
	};

	public static readonly Dictionary<string, int> ToolIdMap = new Dictionary<string, int>
	{
		{ "Axw", 0 },
		{ "How", 1 },
		{ "FishingRod", 2 },
		{ "Pickaxe", 3 },
		{ "WateringCan", 4 },
		{ "MeleeWeapon", 5 },
		{ "Slingshot", 6 }
	};

	public static void add_chest(int posx, int posy, Color color, Mod mod)
	{
		Vector2 key = new Vector2(posx, posy - 1);
		Chest chest = new Chest(playerChest: true);
		NetColor netColor = new NetColor(Color.Brown);
		Type typeFromHandle = typeof(Chest);
		FieldInfo field = typeFromHandle.GetField("tint", BindingFlags.Instance | BindingFlags.NonPublic);
		if (field != null)
		{
			try
			{
				field.SetValue(chest, Color.Brown);
			}
			catch (Exception ex)
			{
				Console.WriteLine("Failed to set the 'tint' field value: " + ex.Message);
			}
		}
		Game1.getFarm().objects.Add(key, chest);
		mod.Monitor.Log($"{TEST_UTILS_LOG} Chest is added at ({posx}, {posy}). time: {DateTime.Now}");
	}

	public static bool callTryToPurchaseItem(object shopMenuInstance, ISalable item, ISalable? held_item, int stockToBuy)
	{
		Type type = shopMenuInstance.GetType();
		MethodInfo method = type.GetMethod("tryToPurchaseItem", BindingFlags.Instance | BindingFlags.NonPublic);
		if (method != null)
		{
			object obj = method.Invoke(shopMenuInstance, new object[5] { item, held_item, stockToBuy, 0, 0 });
			return obj != null && (bool)obj;
		}
		Console.WriteLine("method tryToPurchaseItem unfind!");
		return false;
	}

	public static void print_mouse_pos(Mod mod)
	{
		mod.Monitor.Log($"OldMouseX: {Game1.getOldMouseX(ui_scale: false)}, OldMouseY: {Game1.getOldMouseY(ui_scale: false)}");
		mod.Monitor.Log($"OldMouseX2: {Game1.oldMouseState.X}, OldMouseY: {Game1.oldMouseState.Y}");
	}

	public static void give_thing(Tool tool, Mod mod)
	{
		Inventory items = Game1.player.Items;
		for (int i = 0; i < items.Count; i++)
		{
			if (items[i] == null)
			{
				items[i] = tool;
				mod.Monitor.Log($"{tool} added to player's inventory.", LogLevel.Info);
				return;
			}
		}
		mod.Monitor.Log($"Player's inventory is full. Could not add {tool}.", LogLevel.Warn);
	}

	public static void give_tool(string toolName, Mod mod)
	{
		try
		{
			Inventory items = Game1.player.Items;
			Tool toolInstance = getToolInstance(ToolIdMap[toolName]);
			for (int i = 0; i < items.Count; i++)
			{
				if (items[i] == null)
				{
					items[i] = toolInstance;
					mod.Monitor.Log($"{toolInstance} added to player's inventory.", LogLevel.Info);
					return;
				}
			}
			mod.Monitor.Log($"Player's inventory is full. Could not add {toolInstance}.", LogLevel.Warn);
		}
		catch (Exception ex)
		{
			mod.Monitor.Log($"{ex.Data}");
		}
	}

	private static Tool getToolInstance(int id)
	{
		return id switch
		{
			0 => new Axe(), 
			1 => new Hoe(), 
			2 => new FishingRod(), 
			3 => new Pickaxe(), 
			4 => new WateringCan(), 
			5 => new MeleeWeapon(), 
			6 => new Slingshot(), 
			_ => throw new ArgumentException($"invalid tool ID: {id}"), 
		};
	}

	public static void remove_items(Item item)
	{
		Farmer player = Game1.player;
		player.removeItemFromInventory(item);
	}

	public static void set_time(Mod mod)
	{
		Game1.timeOfDay = 1200;
	}

	public static void tp_player(string location, Mod mod)
	{
		if (Game1.currentLocation != null)
		{
			GameLocation currentLocation = Game1.currentLocation;
			if (Game1.getLocationFromName(location) is Beach)
			{
				Game1.warpFarmer("Beach", 10, 10, flip: false);
				mod.Monitor.Log("Player teleported to the beach.", LogLevel.Info);
				return;
			}
			GameLocation locationFromName = Game1.getLocationFromName(location);
			Game1.warpFarmer(location, 20, 20, flip: false);
			locationFromName.resetForPlayerEntry();
			mod.Monitor.Log("location not found.", LogLevel.Warn);
		}
		else
		{
			mod.Monitor.Log("Player has no location. Cannot teleport.", LogLevel.Warn);
		}
	}

	public static NPC? GetNearestNPC(Farmer player)
	{
		NPC result = null;
		double num = double.MaxValue;
		Vector2 standingPosition = player.getStandingPosition();
		Vector2 value = new Vector2(standingPosition.X / 64f, standingPosition.Y / 64f);
		foreach (NPC character in Game1.currentLocation.characters)
		{
			Vector2 standingPosition2 = character.getStandingPosition();
			Vector2 value2 = new Vector2(standingPosition2.X / 64f, standingPosition2.Y / 64f);
			double num2 = Vector2.Distance(value, value2);
			if (num2 < num)
			{
				num = num2;
				result = character;
			}
		}
		return result;
	}

	public static void enterLoadGameMenu(Mod mod, Action onComplete)
	{
		int bufferFrames = 5;
		EventHandler<UpdateTickedEventArgs> checkEnterLoadGameMenu = null;
		checkEnterLoadGameMenu = delegate
		{
			IClickableMenu activeClickableMenu = Game1.activeClickableMenu;
			if (activeClickableMenu is TitleMenu titleMenu)
			{
				if (bufferFrames <= 0)
				{
					mod.Helper.Events.GameLoop.UpdateTicked -= checkEnterLoadGameMenu;
					titleMenu.performButtonAction("Load");
					onComplete();
				}
				else
				{
					bufferFrames--;
				}
			}
		};
		mod.Helper.Events.GameLoop.UpdateTicked += checkEnterLoadGameMenu;
	}

	public static void loadGame(string which, Mod mod, Action onComplete)
	{
		int bufferFrames = 5;
		EventHandler<UpdateTickedEventArgs> checkLoadGame = null;
		checkLoadGame = delegate
		{
			IClickableMenu activeClickableMenu = Game1.activeClickableMenu;
			if (activeClickableMenu is TitleMenu && TitleMenu.subMenu is LoadGameMenu loadGameMenu)
			{
				if (bufferFrames <= 0)
				{
					mod.Helper.Events.GameLoop.UpdateTicked -= checkLoadGame;
					int index = int.Parse(which);
					LoadGameMenu.MenuSlot menuSlot = loadGameMenu.MenuSlots[index];
					if (menuSlot is LoadGameMenu.SaveFileSlot saveFileSlot)
					{
						saveFileSlot.Activate();
					}
					onComplete();
				}
				else
				{
					bufferFrames--;
				}
			}
		};
		mod.Helper.Events.GameLoop.UpdateTicked += checkLoadGame;
	}

	public static void exitGameToTitle()
	{
		Game1.ExitToTitle();
	}

	public static void give_items(string item_id, int amount)
	{
		StardewValley.Object item = new StardewValley.Object(item_id, amount);
		Game1.player.addItemToInventoryBool(item);
	}

	public static void give_money(int amount)
	{
		Game1.player.Money += amount;
	}

	public static Vector2 getTileLocation(Farmer player)
	{
		Vector2 standingPosition = player.getStandingPosition();
		return new Vector2(standingPosition.X / 64f, standingPosition.Y / 64f);
	}
}
