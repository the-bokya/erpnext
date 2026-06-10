# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and Contributors
# See license.txt

import frappe
from frappe.utils import nowdate

from erpnext.tests.utils import ERPNextTestSuite


class TestNonNumericAcceptance(ERPNextTestSuite):
	def test_acceptance_value_comparison_is_case_insensitive(self):
		create_quality_inspection_parameter("_Test Casefold Parameter")
		inspection = frappe.new_doc("Quality Inspection")
		reading = inspection.append(
			"readings",
			{
				"specification": "_Test Casefold Parameter",
				"numeric": 0,
				"value": "Yes",
				"reading_value": " yes ",
			},
		)

		# "yes" with different casing/whitespace passes a criteria of "Yes"
		inspection.set_status_based_on_acceptance_values(reading)
		self.assertEqual(reading.status, "Accepted")

		reading.reading_value = "no"
		inspection.set_status_based_on_acceptance_values(reading)
		self.assertEqual(reading.status, "Rejected")

		# an unrecorded reading is a draft in progress, not a rejection
		reading.reading_value = "  "
		reading.status = "Accepted"
		inspection.set_status_based_on_acceptance_values(reading)
		self.assertEqual(reading.status, "Accepted")


def create_quality_inspection(**args):
	args = frappe._dict(args)
	qa = frappe.new_doc("Quality Inspection")
	qa.report_date = nowdate()
	qa.inspection_type = args.inspection_type or "Outgoing"
	qa.reference_type = args.reference_type
	qa.reference_name = args.reference_name
	qa.item_code = args.item_code or "_Test Item with QA"
	qa.sample_size = 1
	qa.inspected_by = frappe.session.user
	qa.status = args.status or "Accepted"

	if not args.readings:
		create_quality_inspection_parameter("Size")
		readings = {"specification": "Size", "min_value": 0, "max_value": 10, "reading_1": "5"}
		if args.status == "Rejected":
			readings["reading_1"] = "12"  # status is auto set in child on save
	else:
		readings = args.readings

	if isinstance(readings, list):
		for entry in readings:
			create_quality_inspection_parameter(entry["specification"])
			qa.append("readings", entry)
	else:
		qa.append("readings", readings)

	if not args.do_not_save:
		qa.save()
		if not args.do_not_submit:
			qa.submit()

	return qa


def create_quality_inspection_parameter(parameter):
	if not frappe.db.exists("Quality Inspection Parameter", parameter):
		frappe.get_doc(
			{"doctype": "Quality Inspection Parameter", "parameter": parameter, "description": parameter}
		).insert()
