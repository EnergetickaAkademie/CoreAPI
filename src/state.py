from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
import time
import sys
import os

from enak import Enak, Script

from scenarios.demo import getScript
from scenarios.normal_long import getScript as getNormalLongScript
from scenarios.normal_medium import getScript as getNormalMediumScript
from scenarios.normal_short import getScript as getNormalShortScript
from scenarios.test import getScript as getTestScript
from scenarios.allon import getScript as getAllOnScript
from scenarios.allon_outage import getScript as getAllOnOutageScript
from user_config import get_user_config

# Global debug flag from environment variable
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

def debug_print(message):
	"""Print debug message only if DEBUG is enabled"""
	if DEBUG:
		print(f"DEBUG: {message}")

available_script_generators: Dict[str, Callable[[], Script]] = {
	#"test": getTestScript,
	"workshop - dlouhý": getNormalLongScript,
	"workshop - střední": getNormalMediumScript,
	"workshop - krátký": getNormalShortScript,
	"konference - všechno": getAllOnScript,
	"konference - výpadek": getAllOnOutageScript
}

# Backwards compatibility - generate instances on demand
available_scripts: Dict[str, Script] = {}

def get_fresh_script(scenario_id: str) -> Script:
	"""Get a fresh script instance for the given scenario"""
	if scenario_id in available_script_generators:
		return available_script_generators[scenario_id]()
	elif scenario_id in available_scripts:
		# Fallback for old-style scripts - manually reset state
		script = available_scripts[scenario_id]
		script.current_round_index = 0
		return script
	else:
		raise ValueError(f"Unknown scenario: {scenario_id}")

# Populate available_scripts for backwards compatibility
for scenario_id, generator in available_script_generators.items():
	available_scripts[scenario_id] = generator()

class GameState:
	"""
	Represents the state of the game.
	"""
	def __init__(self, script):
		self.boards: Dict[str, 'BoardState'] = {}
		self.script = script
		self.scenario_id = None

		self.production_range_overrides = {}
		self.consumption_overrides = {}
		self.config_revision = 0

	def bump_config_revision(self):
		self.config_revision = (self.config_revision + 1) & 0xFFFFFFFF

	def get_script(self) -> Script:
		"""
		Returns the script associated with the game state.
		"""
		return self.script
	
	def register_board(self, board_id: str) -> 'BoardState':
		"""
		Registers a new board in the game state.
		"""
		debug_print(f"Registering board: {board_id}")
		if board_id not in self.boards:
			self.boards[board_id] = BoardState(board_id)
			debug_print(f"Board {board_id} registered successfully.")
		return self.boards[board_id]

	def reset_for_new_game(self):
		"""Reset per-game state for all boards while keeping registrations.

		This is invoked when a new scenario is started without explicitly
		calling end_game (lecturer may quickly restart). We must drop any
		stale per-round histories and connected building state so the new
		game starts cleanly.
		"""
		for board in self.boards.values():
			try:
				board.reset_for_new_game()
			except Exception as e:
				print(f"Failed to reset board {board.id}: {e}", file=sys.stderr)
		self.bump_config_revision()

	def get_board(self, board_id: str) -> Optional['BoardState']:
		"""
		Retrieves the board state by ID.
		"""
		debug_print(f"Retrieving board: {board_id}")
		debug_print(str(self.boards))
		if board_id in self.boards:
			return self.boards[board_id]
		return None

	def save_all_boards_current_round_to_history(self):
		"""
		Save the current round data to history for all boards.
		This should be called when advancing to the next round.
		"""
		for board in self.boards.values():
			board.save_current_round_to_history(self.script)

	def finalize_all_boards_current_round(self):
		"""
		Finalize the current round for all boards.
		This should be called when the game ends or when transitioning rounds.
		"""
		for board in self.boards.values():
			board.finalize_current_round(self.script)
			board.clear_connected_buildings()  # Clear buildings when game/scenario ends
	
	def prune_disconnected_boards(self, timeout: float = None):
		"""Remove boards that have been disconnected longer than timeout.

		Called when a game ends (explicitly or naturally) to free memory and
		forget stale building assignments completely.
		"""
		if timeout is None:
			from math import inf
			timeout = BoardState.CONNECTION_TIMEOUT if 'BoardState' in globals() else 5.0
		now = time.time()
		to_remove = []
		for board_id, board in self.boards.items():
			if (now - board.last_updated) > timeout:
				to_remove.append(board_id)
		if to_remove:
			debug_print(f"Pruning stale boards after game end: {to_remove}")
		for board_id in to_remove:
			try:
				del self.boards[board_id]
			except KeyError:
				pass
			
	def get_all_boards_history_summary(self) -> Dict[str, Dict]:
		"""
		Get a summary of all boards' history data.
		"""
		summary = {}
		for board_id, board in self.boards.items():
			summary[board_id] = {
				'round_count': len(board.round_history),
				'rounds': board.round_history.copy(),
				'latest_production': board.production,
				'latest_consumption': board.consumption,
				'current_round_index': board.current_round_index
			}
		return summary

	def get_connection_summary(self) -> Dict[str, any]:
		"""
		Get a summary of board connection status.
		"""
		connected_boards = []
		disconnected_boards = []
		
		for board_id, board in self.boards.items():
			board_info = {
				'board_id': board_id,
				'display_name': board.display_name,
				'time_since_update': board.time_since_last_update()
			}
			
			if board.is_connected():
				connected_boards.append(board_info)
			else:
				board_info['last_updated'] = board.last_updated
				disconnected_boards.append(board_info)
		
		return {
			'total_boards': len(self.boards),
			'connected_count': len(connected_boards),
			'disconnected_count': len(disconnected_boards),
			'connected_boards': connected_boards,
			'disconnected_boards': disconnected_boards
		}

	def get_production_override(self, source):
		return self.production_range_overrides.get(source)

	def set_production_override(self, source, min_val, max_val):
		self.production_range_overrides[source] = (min_val, max_val)
		self.bump_config_revision()

	def clear_production_override(self, source):
		self.production_range_overrides.pop(source, None)
		self.bump_config_revision()

	def get_consumption_override(self, building):
		return self.consumption_overrides.get(building)

	def set_consumption_override(self, building, value):
		self.consumption_overrides[building] = value
		self.bump_config_revision()

	def clear_consumption_override(self, building):
		self.consumption_overrides.pop(building, None)
		self.bump_config_revision()


class BoardState:
	"""
	Represents the state of a board in the application.
	"""
	# Connection timeout in seconds
	CONNECTION_TIMEOUT = 10.0
	
	@staticmethod
	def generate_display_name(board_id: str) -> str:
		"""
		Generate a consistent, user-friendly display name for a board.
		This ensures boards keep the same name when they reconnect.
		First tries to get display_name from users.toml configuration,
		then falls back to generated names.
		"""
		debug_print(f"generate_display_name called for board_id: {board_id}")
		
		# Try to get display name from configuration first
		try:
			config = get_user_config()
			config_display_name = config.get_board_display_name(board_id)
			if config_display_name:
				debug_print(f"Found config display_name: '{config_display_name}' for {board_id}")
				return config_display_name
			else:
				debug_print(f"No config display_name found for {board_id}")
		except Exception as e:
			print(f"WARNING: Could not load display name from config for {board_id}: {e}", file=sys.stderr)
		
		# Fallback to generated names
		debug_print(f"Using fallback name generation for {board_id}")
		if board_id.startswith('board'):
			try:
				# Extract number from board_id like 'board1' -> '1'
				board_number = board_id[5:]  # Remove 'board' prefix
				fallback_name = f"Tým {board_number}"
				debug_print(f"Generated fallback name: '{fallback_name}' for {board_id}")
				return fallback_name
			except (ValueError, IndexError):
				# Fallback if parsing fails
				fallback_name = f"Tým {board_id}"
				debug_print(f"Generated fallback name (error case): '{fallback_name}' for {board_id}")
				return fallback_name
		else:
			# For non-standard board IDs, use the ID directly with Team prefix
			fallback_name = f"Tým {board_id}"
			debug_print(f"Generated fallback name (non-standard): '{fallback_name}' for {board_id}")
			return fallback_name
	
	def __init__(self, id: str):
		self.id = id
		self.display_name = self.generate_display_name(id)
		self.production: int = 0
		self.consumption: int = 0
		self.last_updated: float = time.time()
		self.connected_consumption: List[int] = []
		self.connected_production: List[int] = []
		# History tracking for statistics - now by round (only for game rounds: DAY/NIGHT)
		self.production_history: List[int] = []  # Final values from each completed round
		self.consumption_history: List[int] = []  # Final values from each completed round
		self.round_history: List[int] = []  # Round indices corresponding to history entries
		# Power plant connection and production history by round
		self.powerplant_history: List[Dict[str, Any]] = []  # Power plant data per completed round
		# Track current round to detect round changes
		self.current_round_index: int = -1
		# Power generation by type tracking
		self.power_generation_by_type: Dict[str, float] = {}
		# Connected buildings for persistence across board restarts
		self.connected_buildings: List[Dict[str, Any]] = []

		#the building counts that the boards do not override
		self.authoritative_counts = [0] * len(Enak.Building)
		# Ephemeral transport/firmware metadata, refreshed on each board heartbeat.
		self.network_address = None
		self.ota_port = 8080
		self.firmware_version = None
		self.ota_ready = False
		self.config_schema = 0
		self.firmware_error = None
		self.firmware_protocol = 0
		self.firmware_last_seen = 0.0
		self.firmware_transport = None
		self.firmware_job_id = None
		self.firmware_job_state = None
		self.firmware_job_error = None

	def is_connected(self) -> bool:
		"""
		Check if the board is considered connected based on last update time.
		Returns False if the board hasn't updated within CONNECTION_TIMEOUT seconds.
		"""
		current_time = time.time()
		time_since_update = current_time - self.last_updated
		return time_since_update <= self.CONNECTION_TIMEOUT

	def time_since_last_update(self) -> float:
		"""
		Returns the time in seconds since the last update.
		"""
		return time.time() - self.last_updated

	def update_last_activity(self):
		"""
		Updates the last activity timestamp to mark board as active.
		This should be called for any board communication (polling or posting).
		"""
		self.last_updated = time.time()

	def update_power(self, production: int, consumption: int, script: 'Script' = None):
		"""
		Updates the power production and consumption for the board.
		History is now saved only when explicitly requested (e.g., during next_round).
		"""
		# Determine current round from script and update tracker
		if script:
			self.current_round_index = script.current_round_index
		
		# Update current values
		self.production = production
		self.consumption = consumption
		self.update_last_activity()

	def save_current_round_to_history(self, script: 'Script' = None):
		"""
		Save the current production and consumption values to history.
		Only saves for game rounds (DAY/NIGHT), not for slide rounds.
		This should be called when advancing to the next round.
		"""
		# A final round may be finalized after it was already saved while
		# advancing. Keep history idempotent by round index.
		if self.current_round_index >= 0 and self.round_history and self.round_history[-1] == self.current_round_index:
			return

		# Only save history for game rounds (DAY/NIGHT)
		if script and self.current_round_index >= 0:
			current_round = script.getCurrentRound()
			if current_round and hasattr(current_round, 'getRoundType'):
				from enak import Enak
				round_type = current_round.getRoundType()
				# Only save for DAY and NIGHT rounds, not SLIDE or SLIDE_RANGE
				if round_type in [Enak.RoundType.DAY, Enak.RoundType.NIGHT]:
					self.production_history.append(self.production)
					self.consumption_history.append(self.consumption)
					self.round_history.append(self.current_round_index)
					
					# Save power plant data for this round
					powerplant_data = {
						'round_index': self.current_round_index,
						'round_type': round_type.name,
						'connected_production': self.connected_production.copy(),
						'power_generation_by_type': self.power_generation_by_type.copy(),
						'total_production': self.production,
						'timestamp': time.time()
					}
					self.powerplant_history.append(powerplant_data)
					
					debug_print(f"Board {self.id}: Saved game round {self.current_round_index} ({round_type.name}) to history - Production: {self.production}, Consumption: {self.consumption}, Power plants: {self.power_generation_by_type}")
				else:
					debug_print(f"Board {self.id}: Skipping history save for non-game round {self.current_round_index} ({round_type.name})")
		elif self.current_round_index >= 0:
			# Fallback for when script is not available - save anyway
			self.production_history.append(self.production)
			self.consumption_history.append(self.consumption)
			self.round_history.append(self.current_round_index)
			
			powerplant_data = {
				'round_index': self.current_round_index,
				'round_type': 'UNKNOWN',
				'connected_production': self.connected_production.copy(),
				'power_generation_by_type': self.power_generation_by_type.copy(),
				'total_production': self.production,
				'timestamp': time.time()
			}
			self.powerplant_history.append(powerplant_data)
			
			debug_print(f"Board {self.id}: Saved round {self.current_round_index} to history (no script) - Production: {self.production}, Consumption: {self.consumption}")

	def finalize_current_round(self, script: 'Script' = None):
		"""
		Manually finalize the current round by saving current values to history.
		Useful when game ends or when you want to ensure the last round is captured.
		"""
		self.save_current_round_to_history(script)

	def get_history_for_round(self, round_index: int) -> Optional[tuple]:
		"""
		Get the production and consumption values for a specific round.
		Returns tuple (production, consumption) or None if round not found.
		"""
		try:
			history_index = self.round_history.index(round_index)
			return (self.production_history[history_index], self.consumption_history[history_index])
		except (ValueError, IndexError):
			return None

	def get_powerplant_history_for_round(self, round_index: int) -> Optional[Dict[str, Any]]:
		"""
		Get the power plant data for a specific round.
		Returns power plant data dict or None if round not found.
		"""
		for powerplant_data in self.powerplant_history:
			if powerplant_data['round_index'] == round_index:
				return powerplant_data
		return None

	def get_all_powerplant_history(self) -> List[Dict[str, Any]]:
		"""
		Get all power plant history data.
		"""
		return self.powerplant_history.copy()

	def get_round_indices(self) -> List[int]:
		"""
		Get all round indices that have been recorded in history.
		"""
		return self.round_history.copy()

	def has_unsaved_current_round(self) -> bool:
		"""
		Check if the current round has data that hasn't been saved to history yet.
		Useful to know if finalize_current_round() should be called.
		"""
		return (self.current_round_index >= 0 and 
				(not self.round_history or self.round_history[-1] != self.current_round_index))

	def replace_connected_consumption(self, consumption: List[int]):
		"""
		Replaces the connected consumption list.
		"""
		self.connected_consumption = consumption

	def replace_connected_production(self, production: List[int]):
		"""
		Replaces the connected production list.
		"""
		self.connected_production = production

	def get_connected_consumption(self) -> List[int]:
		"""
		Returns the connected consumption list.
		"""
		return self.connected_consumption

	def get_connected_production(self) -> List[int]:
		"""
		Returns the connected production list.
		"""
		return self.connected_production

	def update_power_generation_by_type(self, power_type: str, generation: float):
		"""
		Updates the power generation for a specific power plant type.
		"""
		self.power_generation_by_type[power_type] = generation
		self.update_last_activity()

	def get_power_generation_by_type(self, power_type: str) -> float:
		"""
		Returns the power generation for a specific power plant type.
		"""
		return self.power_generation_by_type.get(power_type, 0.0)

	def get_all_power_generation_by_type(self) -> Dict[str, float]:
		"""
		Returns all power generation data by type.
		"""
		return self.power_generation_by_type.copy()

	def set_power_generation_data(self, generation_data: Dict[str, float]):
		"""
		Sets multiple power generation values at once.
		"""
		self.power_generation_by_type.update(generation_data)
		self.update_last_activity()

	def add_connected_building(self, uid: str, building_type: int):
		"""
		Add a connected building to the board state.
		"""
		# Remove if already exists
		self.connected_buildings = [b for b in self.connected_buildings if b['uid'] != uid]
		self.connected_buildings.append({'uid': uid, 'building_type': building_type})
		self.update_last_activity()

	def register_building(self, uid: str, building_type: int) -> str:
		"""Register one physical NFC tag exactly once.

		Returns ``added``, ``duplicate``, ``conflict``, ``invalid``, or
		``capacity`` so the HTTP layer can provide a stable response without
		double-counting retried requests.
		"""
		if not uid or not 0 <= building_type < len(self.authoritative_counts):
			return "invalid"

		for building in self.connected_buildings:
			if building.get('uid') != uid:
				continue
			if building.get('building_type') == building_type:
				self.update_last_activity()
				return "duplicate"
			return "conflict"

		if self.authoritative_counts[building_type] >= 255:
			return "capacity"

		self.connected_buildings.append({'uid': uid, 'building_type': building_type})
		self.authoritative_counts[building_type] += 1
		self.update_last_activity()
		return "added"

	def remove_connected_building(self, uid: str):
		"""
		Remove a connected building from the board state.
		"""
		self.connected_buildings = [b for b in self.connected_buildings if b['uid'] != uid]
		self.update_last_activity()

	def get_connected_buildings(self) -> List[Dict[str, Any]]:
		"""
		Get the list of connected buildings.
		"""
		return self.connected_buildings.copy()

	def clear_connected_buildings(self):
		"""
		Clear all connected buildings (e.g., when game ends).
		"""
		self.connected_buildings = []
		self.update_last_activity()

	def clear_registered_buildings(self):
		"""Clear every NFC building registration and its authoritative count.

		This intentionally leaves production settings and round history intact so
		it can be used during an active scenario as an administrative reset.
		"""
		self.connected_buildings = []
		self.authoritative_counts = [0] * len(Enak.Building)
		self.update_last_activity()

	def reset_for_new_game(self):
		"""Reset transient state for a fresh scenario while keeping identity.

		Does NOT remove the board registration or display_name. Clears:
		- current production/consumption values
		- any connected production/consumption arrays
		- per-round histories
		- power plant generation tracking
		- connected buildings
		- current_round_index
		"""
		self.production = 0
		self.consumption = 0
		self.connected_consumption = []
		self.connected_production = []
		self.production_history.clear()
		self.consumption_history.clear()
		self.round_history.clear()
		self.powerplant_history.clear()
		self.current_round_index = -1
		self.power_generation_by_type.clear()
		self.connected_buildings = []
		self.update_last_activity()

		self.authoritative_counts = [0] * len(Enak.Building)

	def to_dict(self):
		"""
		Returns a dictionary representation of the board state.
		"""
		return {
			"board_id": self.id,
			"display_name": self.display_name,
			"production": self.production,
			"consumption": self.consumption,
			"last_updated": self.last_updated,
			"connected": self.is_connected(),
			"time_since_update": self.time_since_last_update(),
			"connected_consumption": self.connected_consumption,
			"connected_production": self.connected_production,
			"production_history": self.production_history,
			"consumption_history": self.consumption_history,
			"round_history": self.round_history,
			"powerplant_history": self.powerplant_history,
			"current_round_index": self.current_round_index,
			"power_generation_by_type": self.power_generation_by_type,
			"connected_buildings": self.connected_buildings,
			"authoritative_counts": self.authoritative_counts,
			"network_address": self.network_address,
			"ota_port": self.ota_port,
			"firmware_version": self.firmware_version,
			"ota_ready": self.ota_ready,
			"config_schema": self.config_schema,
			"firmware_error": self.firmware_error,
			"firmware_protocol": self.firmware_protocol,
			"firmware_last_seen": self.firmware_last_seen,
			"firmware_transport": self.firmware_transport,
			"firmware_job_id": self.firmware_job_id,
			"firmware_job_state": self.firmware_job_state,
			"firmware_job_error": self.firmware_job_error
		}

	###### for board interactions with the building counts

	def add_building(self, building_type: int):
		if 0 <= building_type < len(self.authoritative_counts):
			self.authoritative_counts[building_type] += 1
			self.update_last_activity()

	def set_counts(self, counts: list):
		if (len(counts) != len(Enak.Building) or
			not all(isinstance(value, int) and 0 <= value <= 255 for value in counts)):
			raise ValueError("Building counts must be 18 byte-sized integers")
		self.authoritative_counts = counts[:]

		# The lecturer UI may reduce a count independently of the physical NFC
		# registrations. Drop registrations that no longer fit the authoritative
		# count; otherwise a tag removed in the UI would remain a duplicate and
		# could never be scanned back in.
		remaining = counts[:]
		kept_buildings = []
		for building in self.connected_buildings:
			building_type = building.get("building_type")
			if (isinstance(building_type, int) and
				0 <= building_type < len(remaining) and
				remaining[building_type] > 0):
				kept_buildings.append(building)
				remaining[building_type] -= 1
		self.connected_buildings = kept_buildings
		self.update_last_activity()

	def get_counts(self) -> list:
		return self.authoritative_counts[:]

	def get_persistent_state(self) -> Dict[str, Any]:
		"""Return the small restart-safe part of board state."""
		return {
			"authoritative_counts": self.get_counts(),
			"connected_buildings": self.get_connected_buildings(),
		}

	def restore_persistent_state(self, data: Dict[str, Any]):
		"""Restore validated registration/building state from durable storage."""
		counts = data.get("authoritative_counts", [])
		buildings = data.get("connected_buildings", [])

		if (isinstance(counts, list) and
			len(counts) == len(self.authoritative_counts) and
			all(isinstance(value, int) and 0 <= value <= 255 for value in counts)):
			self.authoritative_counts = counts[:]

		valid_buildings = []
		seen_uids = set()
		if isinstance(buildings, list):
			for building in buildings:
				if not isinstance(building, dict):
					continue
				uid = building.get("uid")
				building_type = building.get("building_type")
				if (isinstance(uid, str) and uid and uid not in seen_uids and
					isinstance(building_type, int) and
					0 <= building_type < len(self.authoritative_counts)):
					seen_uids.add(uid)
					valid_buildings.append({"uid": uid, "building_type": building_type})
		self.connected_buildings = valid_buildings
		# Restored identity is not proof that the physical board is online.
		self.last_updated = 0.0
