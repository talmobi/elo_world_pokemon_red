import itertools
import json
import os
import random
import subprocess
import time
import struct
import uuid
from typing import Iterable, Tuple
import shutil
import ffmpeg

WORKING_DIR_BASE = "D:/elo_world_pokemon_red_scratch"
OUTPUT_BASE = "../elo_world_pokemon_red_output"

BGB_PATH = "bgb/bgb.exe"
LOSSLESS = True

ROM_IMAGE = "Pokemon - Red Version (UE) [S][!].gb"
BASE_SAVE = "basestate.sn1"
AI_SAVE = "ai_choose_state.sn1"

BATTLE_SAVE = "battlestate.sn1"
OUT_SAVE = "outstate.sn1"
OUT_DEMO = "outdemo.dem"


def load_json(path: str) -> dict:
	with open(path, 'r', encoding='utf-8') as f:
		return json.load(f)


def load_memory_map(path: str) -> Tuple[dict, dict]:
	base = load_json(path)
	return {int(key, 16): value for key, value in base.items()}, {value: int(key, 16) for key, value in base.items()}


pokemon_names = load_json("pokemon_names.json")
trainers = load_json("trainers.json")
characters, reverse_characters = load_memory_map('charmap.json')
moves, reverse_moves = load_memory_map('moves.json')
items, reverse_items = load_memory_map('items.json')

GLOBAL_OFFSET = 0xBBC3

x_id = 201
x_index = 1
y_id = 202
y_index = 2

PLAYER_NAME = 0xd158
ENEMY_TRAINER_NAME = 0xd04a
POKEMON_NAME_LENGTH = 11
TRAINER_NAME_LENGTH = 13
NAME_TERMINATOR = 0x50

PARTY_NICKNAMES = 0xd2b5

PARTY_MON_OT = 0xd273
ENEMY_MON_OT = 0xd9ac

TRAINER_CLASS = 0xd059
TRAINER_CLASS_WITHOUT_OFFSET = 0xd031
TRAINER_INSTANCE = 0xd05d

PARTY_MON_LIST = 0xd164
ENEMY_PARTY_MON_LIST = 0xd89d
PARTY_MON_HP = 0xd16c

PARTY_COUNT = 0xd163
ENEMY_PARTY_COUNT = 0xd89c

PARTY_MONS = 0xd16b
ENEMY_PARTY_MONS = 0xd8a4

LONE_ATTACK_NO = 0xd05c

PARTY_STRUCT_SIZE = 0x2B

PLAYER_SELECTED_MOVE = 0xccdc
ENEMY_SELECTED_MOVE = 0xccdd

BATTLE_MON = 0xd014
BATTLE_MON_HP = 0xD015
BATTLE_MON_PARTY_POS = 0xd017
BATTLE_MON_MOVES = 0xd01c
BATTLE_MON_SPEED = 0xd029
BATTLE_MON_PP = 0xd02d
ENEMY_BATTLE_MON = 0xcfe5
BATTLE_MON_SIZE = 0x1c

DISABLED_MOVE = 0xd06d
ENEMY_DISABLED_MOVE = 0xd072

ENEMY_ITEM_USED = 0xcf05
AI_ACTION_COUNT = 0xccdf

DIVISOR_OFFSET = 0x220
PC_OFFSET = 0xDA
TOTAL_CLOCKS_OFFSET = 0x232

SWITCH_CALL_OFFSET = 0x6765
DISPLAY_BATTLE_MENU_OFFSET = 0x4eb6
PARTY_MENU_INIT_OFFSET = 0x1420

TRAINER_WIN_OFFSET = 0x4696
ENEMY_WIN_OFFSET = 0x4837

MOVE_LIST_INDEX = 0xcc2e

BAG_ITEM_COUNT = 0xd31d
BAG_ITEMS = 0xd31e

A_BUTTON = 0b00000001
B_BUTTON = 0b00000010
RIGHT_BUTTON = 0b00010000
LEFT_BUTTON = 0b00100000
UP_BUTTON = 0b01000000
DOWN_BUTTON = 0b10000000


def byte_to_pokestring(byte_array: Iterable[int]) -> str:
	return "".join(characters[b_int] if (b_int := int(b)) in characters else f"[0x{b:x}]" for b in byte_array)


def name_to_bytes(name: str, length: int = POKEMON_NAME_LENGTH) -> Iterable[int]:
	return (reverse_characters[name[i]] if i < len(name) else NAME_TERMINATOR for i in range(length))


def load_trainer_info(trainer_id: int, trainer_index: int, lone_move_number: int, battle_save: str = BATTLE_SAVE,
                      out_save: str = OUT_SAVE) -> None:
	save = load_save(BASE_SAVE)
	save[TRAINER_CLASS - GLOBAL_OFFSET] = trainer_id
	save[TRAINER_INSTANCE - GLOBAL_OFFSET] = trainer_index
	save[LONE_ATTACK_NO - GLOBAL_OFFSET] = lone_move_number
	write_file(battle_save, save)

	subprocess.call([BGB_PATH, '-rom', battle_save,
	                 '-ab', 'da44//w',
	                 '-hf',
	                 '-nobatt',
	                 '-stateonexit', out_save])


def get_trainer_string(trainer_class: dict, trainer_instance: dict) -> str:
	location = trainer_instance['location']
	return f"a {trainer_class['class']} from {location if location != '' else 'somewhere'} who has a " + \
	       ", ".join(f"level {pokemon['level']} {pokemon['species']}" for pokemon in trainer_instance["party"]) + \
	       f" (class id: {trainer_class['id']}, instance number: {trainer_instance['index']})"


def get_ai_action(out_save: str = OUT_SAVE) -> Tuple[int, int, bool]:
	subprocess.call([BGB_PATH, '-rom', out_save,
	                 '-br', '4349,6765',
	                 '-ab', 'cf05//r',
	                 '-hf',
	                 '-nobatt',
	                 '-stateonexit', out_save])
	save = load_save(out_save)
	move_id = get_value(save, ENEMY_SELECTED_MOVE, 1)[0]
	item_id = get_value(save, ENEMY_ITEM_USED, 1)[0]
	program_counter = get_program_counter(save)
	return move_id, item_id, program_counter == SWITCH_CALL_OFFSET


def get_random_trainer() -> Tuple[dict, dict]:
	trainer = random.choice(trainers)
	trainer_instance = random.choice(trainer["instances"])
	return trainer, trainer_instance


def get_trainer_by_id(trainer_id: int, instance_index: int) -> Tuple[dict, dict]:
	for trainer in trainers:
		if trainer["id"] == trainer_id:
			return trainer, trainer["instances"][instance_index - 1]
	raise ValueError("Trainer ID not found")


def get_string(source: bytearray, offset: int, length: int) -> str:
	return byte_to_pokestring(get_value(source, offset, length))


def get_value(source: bytearray, offset: int, length: int) -> bytearray:
	return source[offset - GLOBAL_OFFSET:offset + length - GLOBAL_OFFSET]


def set_value(target: bytearray, offset: int, source: Iterable[int], length: int) -> None:
	target[offset - GLOBAL_OFFSET:offset + length - GLOBAL_OFFSET] = source


def copy_values(source: bytearray, source_offset: int, target: bytearray, target_offset: int, length: int) -> None:
	target[target_offset - GLOBAL_OFFSET:target_offset + length - GLOBAL_OFFSET] = source[
	                                                                               source_offset - GLOBAL_OFFSET:source_offset + length - GLOBAL_OFFSET]


def write_file(file: str, save: bytearray) -> None:
	with open(file, 'wb') as f:
		f.write(save)


def load_save(file: str) -> bytearray:
	with open(file, 'rb') as f:
		save = bytearray(f.read())
	return save


def randomize_rdiv(source: bytearray):
	source[DIVISOR_OFFSET:DIVISOR_OFFSET + 3] = (random.randint(0, 255) for _ in range(3))


def get_total_clocks(source: bytearray) -> int:
	return struct.unpack_from("<Q", source[TOTAL_CLOCKS_OFFSET:])[0]


def get_program_counter(source: bytearray) -> int:
	return (source[PC_OFFSET + 1] << 8) | source[PC_OFFSET]


def make_button_sequence(buttons: Iterable[int]) -> Iterable[int]:
	zero = itertools.repeat(0)
	buffer_size = 12
	return [
		half_press
		for full_press in zip(zero, buttons, buttons, *([zero] * buffer_size))
		for half_press in full_press
	]


def generate_demo(buttons: Iterable[int], buffer_button: int = B_BUTTON, buffer_size: int = 1000) -> bytearray:
	return bytearray([
		*make_button_sequence(buttons),
		*make_button_sequence([buffer_button] * buffer_size)
	])


def select_move(current_move: int, target_move: int) -> bytearray:
	if target_move < current_move:
		move_button = UP_BUTTON
		move_amount = current_move - target_move
	else:
		move_button = DOWN_BUTTON
		move_amount = target_move - current_move
	return generate_demo([
		B_BUTTON,
		UP_BUTTON,
		LEFT_BUTTON,
		A_BUTTON,
		0, 0,
		*([move_button] * move_amount),
		A_BUTTON
	])


def select_switch() -> bytearray:
	return generate_demo([
		UP_BUTTON,
		RIGHT_BUTTON,
		A_BUTTON
	])


def get_move_index(battle_state: bytearray, move_id: int) -> int:
	battle_moves = get_value(battle_state, BATTLE_MON_MOVES, 4)
	return battle_moves.index(move_id) if move_id in battle_moves else 0


def get_pokemon_to_switch_to(battle_state: bytearray) -> int:
	current_pokemon = get_value(battle_state, BATTLE_MON_PARTY_POS, 1)[0]
	for i in range(6):
		if i == current_pokemon:
			continue
		party_mon_hp = get_value(battle_state, PARTY_MON_HP + i * PARTY_STRUCT_SIZE, 2)
		if party_mon_hp[0] | party_mon_hp[1]:
			return i
	return 0


def choose_pokemon(index: int) -> bytearray:
	return generate_demo([
		0, 0, 0, 0, 0,
		*([DOWN_BUTTON] * index),
		A_BUTTON,
		0, 0, 0, 0, 0,
		A_BUTTON
	])


def use_item():
	return generate_demo([
		0, 0, 0, 0,
		DOWN_BUTTON,
		LEFT_BUTTON,
		A_BUTTON,
		0, 0, 0, 0, 0,
		A_BUTTON,
		A_BUTTON
	])


def copy_dependencies(working_dir):
	for file in [ROM_IMAGE]:
		shutil.copyfile(file, f"{working_dir}/{file}")


def battle_x_as_y(your_class, your_instance, enemy_class, enemy_instance, run_number="", save_movie=True):
	working_dir = f"{WORKING_DIR_BASE}/{run_number}"
	os.makedirs(working_dir, exist_ok=True)

	rom_image_path = f"{working_dir}/{ROM_IMAGE}"
	shutil.copyfile(ROM_IMAGE, rom_image_path)

	movie_path = f"{working_dir}/movies"
	movie_index = 0

	bgb_options = ["-hf", "-nowarn", "-nobatt"]
	if save_movie:
		os.makedirs(movie_path)
		bgb_options = [*bgb_options,
		               "-set", "RecordAVI=1",
		               "-set", "WavFileOut=1",
		               "-set", f"RecordAVIfourCC={'cscd' if LOSSLESS else 'X264'}",
		               "-set", "RecordHalfSpeed=1",
		               "-set", f"RecordPrefix={movie_path}/movie{movie_index:05}",
		               ]

	battle_save_path = f"{working_dir}/{BATTLE_SAVE}"
	out_save_path = f"{working_dir}/{OUT_SAVE}"
	out_demo_path = f"{working_dir}/{OUT_DEMO}"

	base = load_save(BASE_SAVE)

	print("getting trainer info")
	start = time.time()
	load_trainer_info(your_class["id"], your_instance["index"],
	                  your_instance["loneMoves"] if "loneMoves" in your_instance else 0,
	                  battle_save_path, out_save_path)
	print("Got trainer info in ", time.time() - start)

	new = load_save(out_save_path)
	copy_values(new, ENEMY_TRAINER_NAME, base, PLAYER_NAME, POKEMON_NAME_LENGTH - 1)
	set_value(base, PLAYER_NAME + POKEMON_NAME_LENGTH - 1, [NAME_TERMINATOR], 1)

	copy_values(new, ENEMY_PARTY_COUNT, base, PARTY_COUNT, 1)
	copy_values(new, ENEMY_PARTY_MON_LIST, base, PARTY_MON_LIST, 7)
	copy_values(new, ENEMY_PARTY_MONS, base, PARTY_MONS, PARTY_STRUCT_SIZE * 6)

	party_size = get_value(new, ENEMY_PARTY_COUNT, 1)[0]
	enemy_mons = get_value(new, ENEMY_PARTY_MONS, PARTY_STRUCT_SIZE * party_size)
	for i in range(party_size):
		pokemon_index = enemy_mons[(PARTY_STRUCT_SIZE + 1) * i] - 1
		pokemon_name = name_to_bytes(pokemon_names[str(pokemon_index)])
		set_value(base, PARTY_NICKNAMES + POKEMON_NAME_LENGTH * i, pokemon_name, POKEMON_NAME_LENGTH)
		copy_values(new, ENEMY_TRAINER_NAME, base, PARTY_MON_OT + POKEMON_NAME_LENGTH * i, POKEMON_NAME_LENGTH)

	set_value(base, TRAINER_CLASS, [enemy_class["id"]], 1)
	set_value(base, TRAINER_INSTANCE, [enemy_instance["index"]], 1)

	if "loneMoves" in enemy_instance:
		set_value(base, LONE_ATTACK_NO, [enemy_instance["loneMoves"]], 1)

	print(f"You are {get_trainer_string(your_class, your_instance)}")
	print(f"Your opponent is {get_trainer_string(enemy_class, enemy_instance)}")

	write_file(battle_save_path, base)
	write_file(out_demo_path, generate_demo([]))

	total_clocks = get_total_clocks(base)

	using_item = False

	while True:
		breakpoint_condition = f"TOTALCLKS>${total_clocks:x}"
		subprocess.call([BGB_PATH, battle_save_path, *bgb_options,
		                 "-br", f"4eb6/{breakpoint_condition},"
		                        f"1420/{breakpoint_condition},"
		                        f"4696/{breakpoint_condition},"
		                        f"4837/{breakpoint_condition}",
		                 "-stateonexit", battle_save_path,
		                 "-demoplay", out_demo_path])

		battle_state = load_save(battle_save_path)
		ai_base = load_save(AI_SAVE)

		total_clocks = get_total_clocks(battle_state)
		pc = get_program_counter(battle_state)

		if pc == PARTY_MENU_INIT_OFFSET:
			if using_item:
				button_sequence = choose_pokemon(get_value(battle_state, BATTLE_MON_PARTY_POS, 1)[0])
				using_item = False
			else:
				button_sequence = choose_pokemon(get_pokemon_to_switch_to(battle_state))
		elif pc == TRAINER_WIN_OFFSET:
			print(f"{your_class['class']} wins!")
			win = True
			break
		elif pc == ENEMY_WIN_OFFSET:
			print(f"{enemy_class['class']} wins!")
			win = False
			break
		else:
			using_item = False
			copy_values(battle_state, BATTLE_MON, ai_base, ENEMY_BATTLE_MON, BATTLE_MON_SIZE - 1)
			copy_values(battle_state, ENEMY_BATTLE_MON, ai_base, BATTLE_MON, BATTLE_MON_SIZE - 1)

			copy_values(battle_state, PARTY_COUNT, ai_base, ENEMY_PARTY_COUNT, 1)
			copy_values(battle_state, DISABLED_MOVE, ai_base, ENEMY_DISABLED_MOVE, 1)

			copy_values(battle_state, ENEMY_PARTY_MON_LIST, ai_base, PARTY_MON_LIST, 7)
			copy_values(battle_state, ENEMY_PARTY_MONS, ai_base, PARTY_MONS, PARTY_STRUCT_SIZE * 6)
			copy_values(battle_state, PARTY_MON_LIST, ai_base, ENEMY_PARTY_MON_LIST, 7)
			copy_values(battle_state, PARTY_MONS, ai_base, ENEMY_PARTY_MONS, PARTY_STRUCT_SIZE * 6)

			set_value(ai_base, TRAINER_CLASS, [your_class["id"]], 1)
			set_value(ai_base, TRAINER_CLASS_WITHOUT_OFFSET, [your_class["id"] - 200], 1)

			set_value(ai_base, BATTLE_MON_SPEED, [0, 0], 2)
			set_value(ai_base, PLAYER_SELECTED_MOVE, [reverse_moves["COUNTER"]], 1)
			set_value(ai_base, ENEMY_ITEM_USED, [0], 1)
			set_value(ai_base, AI_ACTION_COUNT, [3], 1)

			randomize_rdiv(ai_base)

			write_file(out_save_path, ai_base)
			move_id, item_id, switch = get_ai_action(out_save_path)

			print("Move:", moves[move_id], "Item:", items[item_id], "Switch?:", "YES" if switch else "NO")

			if switch:
				button_sequence = select_switch()
			elif item_id:
				set_value(battle_state, BAG_ITEM_COUNT, [1], 1)
				set_value(battle_state, BAG_ITEMS, [item_id, 1, 0xFF], 3)

				using_item = True
				button_sequence = use_item()
			else:
				target_move_index = get_move_index(battle_state, move_id)
				current_move_index = get_value(battle_state, MOVE_LIST_INDEX, 1)[0]
				button_sequence = select_move(current_move_index, target_move_index)

		set_value(battle_state, BATTLE_MON_PP, [0xff, 0xff, 0xff, 0xff], 4)

		write_file(battle_save_path, battle_state)
		write_file(out_demo_path, button_sequence)

		if save_movie:
			movie_index += 1
			bgb_options[-1] = f"RecordPrefix={movie_path}/movie{movie_index:05}"

	for file in [battle_save_path, out_save_path, out_demo_path, rom_image_path]:
		os.remove(file)

	output_dir = OUTPUT_BASE
	output_movie = f"{output_dir}/{run_number}.mp4"
	os.makedirs(output_dir, exist_ok=True)

	if save_movie:
		files = [f"{movie_path}/{f}" for f in os.listdir(movie_path)]
		files.sort()
		videos = [ffmpeg.input(f).setpts("5/3*PTS") for f in files if f.endswith(".avi")]
		audios = [ffmpeg.input(f) for f in files if f.endswith(".wav")]
		clip_count = len(videos)
		video_track = ffmpeg.concat(*[clip for track in zip(videos, audios) for clip in track], v=1, a=1, n=clip_count)
		print(ffmpeg.output(video_track, output_movie, r=30).compile())
		ffmpeg.output(video_track, output_movie, r=30, audio_bitrate=64000, ar=16000).run()
		for f in files:
			os.remove(f)
		os.rmdir(movie_path)

	os.rmdir(working_dir)
	return win


def main():
	your_class, your_instance = get_random_trainer()
	# your_class, your_instance = get_trainer_by_id(229, 1)
	enemy_class, enemy_instance = get_random_trainer()
	# enemy_class, enemy_instance = get_trainer_by_id(230, 22)

	battle_x_as_y(your_class, your_instance, enemy_class, enemy_instance, run_number=str(uuid.uuid4()))


if __name__ == '__main__':
	main()
