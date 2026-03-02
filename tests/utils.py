from typing import Any, TypeVar

T = TypeVar("T")


def find_elements_of_type(elements: list[Any], element_type: type[T]) -> list[T]:
    return [elem for elem in elements if isinstance(elem, element_type)]


def assert_element_of_type(elements: list[Any], element_type: type[T]) -> T:
    elements = find_elements_of_type(elements, element_type)
    assert elements, f"No element of type {element_type.__name__} found"
    assert len(elements) == 1, f"More than one element of type {element_type.__name__} found"
    return elements[0]


def assert_elements_of_type(elements: list[Any], element_type: type[T], count: int) -> list[T]:
    elements = find_elements_of_type(elements, element_type)
    assert len(elements) == count, f"Expected {count} elements of type {element_type.__name__}, found {len(elements)}"
    return elements
