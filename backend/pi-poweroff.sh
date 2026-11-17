#!/bin/sh
# Safe Pi shutdown for the panel's Power button.
# The 2 s pause lets the HTTP reply (and the shutdown message) reach the
# panel before the network dies.
sleep 2
exec /sbin/poweroff
