# lib/aiko/button.py: version: 2020-01-19 06:00 v05
#
# Usage
# ~~~~~
# import aiko.button
# aiko.button.initialise()
#
# def handler(number, state):
#   print("Button {}: {}".format(number, "press" if state else "release"))
# aiko.button.add_button_handler(handler, [16, 17])
# aiko.button.add_touch_handler(handler, [12, 14, 15, 27])
# aiko.button.remove_handler(handler)
#
# def slider_handler(number, state, value):
#   print("Slider {}: {} {}".format(number, state, value))
# aiko.button.add_slider_handler(slider_handler, 12, 15)
# aiko.button.add_slider_handler(slider_handler, 14, 27)
# aiko.button.remove_handler(slider_handler)
#
# To Do
# ~~~~~
# - Slider --> Console log display
# - Ensure add/remove handlers is thread-safe !
# - Add short versus long button press
# - Add holding down multiple buttons simultaneously
# - After remove_handler(), can't re-use existing Button ?!?
# - Fix remove_handler(): Clean-up Button, when no handlers left

from machine import disable_irq, enable_irq, Pin, TouchPad

from aiko.common import map_value
import aiko.event as event

buttons = []
pin_numbers = []
pins = []
pins_active = []  ### globally shared and writable by interrupt handler ###
touch_buttons = []

slider_handlers = []  # [(slider_handler, lower_button, upper_button), ...]
SLIDER_HANDLER = 0
LOWER_BUTTON = 1
UPPER_BUTTON = 2
TOUCH_THRESHOLD = 150

class Button:
  def __init__(self, driver, pin_number, continuous=False):
    self.driver = driver  # Pin or TouchPad
    self.pin_number = pin_number
    self.continuous = continuous
    self.cache = 300
    self.handlers = []
    self.slider_state = 0
    self.state = False

  def call_handlers(self):
    for handler in self.handlers:
      handler(self.pin_number, self.state)

  def get_state(self):
    return self.state

  def set_state(self, state):
    self.state = state

  def value(self, digital=True, use_cache=True):
    result = None
    if isinstance(self.driver, Pin):
      result = not self.driver.value()  # button pulls down input to ground
    if isinstance(self.driver, TouchPad):
      if not use_cache:
        self.cache = self.driver.read()
      result = self.cache
      if digital:
        result = result < TOUCH_THRESHOLD
    return result

def add_button_handler(handler, gpio_pin_numbers):
  for pin_number in gpio_pin_numbers:
    button = create_gpio_button(pin_number)
    button.handlers.append(handler)

def add_slider_handler(handler, lower_pin_number, upper_pin_number):
  lower_button = create_touch_button(lower_pin_number)
  upper_button = create_touch_button(upper_pin_number)
  lower_button.slider = 0
  slider_handlers.append((handler, lower_button, upper_button))

def add_touch_handler(handler, touch_pin_numbers):
  for pin_number in touch_pin_numbers:
    button = create_touch_button(pin_number)
    button.handlers.append(handler)

def create_button(pin, pin_number, continuous=False):
  button = Button(pin, pin_number, continuous)
  buttons.append(button)
  pins.append(pin)
  pin_numbers.append(pin_number)
  return button

def create_gpio_button(pin_number, continuous=False):
  if pin_number in pin_numbers:
    button = buttons[pin_numbers.index(pin_number)]
#   if not isinstance(button, Pin):
#     raise Exception("Existing button {} isn't GPIO".format(pin_number))
  else:
    pin = Pin(pin_number, Pin.IN, Pin.PULL_UP)
    pin.irq(lambda p:pin_change_handler(p),
              trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING)
    button = create_button(pin, pin_number)
  button.continuous = continuous
  return button

def create_touch_button(pin_number, continuous=False):
  if pin_number in pin_numbers:
    button = buttons[pin_numbers.index(pin_number)]
#   if not isinstance(button, TouchPad):
#     raise Exception("Existing button {} isn't TouchPad".format(pin_number))
  else:
    touch_pad = TouchPad(Pin(pin_number))
    button = create_button(touch_pad, pin_number)
    touch_buttons.append(button)
  button.continuous = continuous
  return button

def remove_handler(handler):
  for button in buttons:
    handlers = [handler for handler in button.handlers]
    if handler in handlers:
      button.handlers.remove(handler)
  handlers = [handler for handler in slider_handlers]
  for slider_handler in handlers:
    if slider_handler[0] == handler:
      slider_handlers.remove(slider_handler)

def button_handler():  # software timer event handler
# microPython doesn't support TouchPad interrupts :(
  for touch_button in touch_buttons:
    if touch_button.value(use_cache=False):
      if not touch_button.get_state():
        irq_state = disable_irq()
        pins_active.append(touch_button.driver)
        enable_irq(irq_state)

  irq_state = disable_irq()
  local_pins_active = [pin for pin in pins_active]
  enable_irq(irq_state)

  for pin in local_pins_active:
    button = buttons[pins.index(pin)]
    if button.value():
      call = button.continuous or not button.get_state()
      button.set_state(True)
      if call:
        button.call_handlers()
    else:  # button no longer active
      irq_state = disable_irq()
      pins_active.remove(pin)
      enable_irq(irq_state)
      button.set_state(False)
      button.call_handlers()

  for slider_handler in slider_handlers:
    lower_value = slider_handler[LOWER_BUTTON].value(digital=False)
    upper_value = slider_handler[UPPER_BUTTON].value(digital=False)
    handler = slider_handler[SLIDER_HANDLER]
    pin_number = slider_handler[LOWER_BUTTON].pin_number
    slider_state = slider_handler[LOWER_BUTTON].slider_state

    if lower_value < TOUCH_THRESHOLD or upper_value < TOUCH_THRESHOLD:
      value = int(map_value(lower_value - upper_value, -180, 180, 0, 100))
      handler(pin_number, slider_state, value)
      if slider_state == 0:
        slider_handler[LOWER_BUTTON].slider_state = 1
    elif slider_state == 1:
      handler(pin_number, 2, None)
      slider_handler[LOWER_BUTTON].slider_state = 0

def pin_change_handler(pin):  # hardware pin interrupt handler
  if not pin.value():         # button pulls down input to ground
    if not pin in pins_active:
      pins_active.append(pin)

def initialise(poll_rate=200):  # 5 Hz
  event.add_timer_handler(button_handler, poll_rate)
