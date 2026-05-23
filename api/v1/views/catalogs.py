from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from pot.models import CustomUser, Inventory, InventorySpace, Property, Ticket


class CatalogView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                'roles': self._choices(CustomUser.Role),
                'document_types': self._choices(CustomUser.DocumentType),
                'property_types': self._choices(Property.Type),
                'property_statuses': self._choices(Property.Status),
                'inventory_conditions': self._choices(InventorySpace.Condition),
                'inventory_types': self._choices(Inventory.Type),
                'inventory_statuses': self._choices(Inventory.Status),
                'ticket_statuses': self._ticket_statuses(),
                'ticket_damage_types': self._ticket_damage_types(),
                'ticket_priorities': self._ticket_priorities(),
                'ticket_status_transitions': self._ticket_status_transitions(),
            }
        )

    @staticmethod
    def _choices(choices_class):
        return [{'value': value, 'label': label} for value, label in choices_class.choices]

    @staticmethod
    def _ticket_statuses():
        return CatalogView._choices(Ticket.Status)

    @staticmethod
    def _ticket_damage_types():
        return CatalogView._choices(Ticket.DamageType)

    @staticmethod
    def _ticket_priorities():
        return CatalogView._choices(Ticket.Priority)

    @staticmethod
    def _ticket_status_transitions():
        return {
            'OPEN': ['ACCEPTED', 'REJECTED'],
            'ACCEPTED': ['IN_PROGRESS'],
            'IN_PROGRESS': ['CLOSED'],
            'active_to_rejected': 'Cualquier estado activo puede pasar a REJECTED con motivo.',
        }
