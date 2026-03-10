### ERPNext Workplan

This is an App for ERPNext allows leave calculations based on expected working hours per day. It will calculate the available leave budgets based on expected working hours per day (e.g. a person that works only 20 instead of 40 hours per week, will only receive 50% of the regular leave budget). For Leave Applications, it will also only deduct the actual work time on the given leave days (e.g. taking off a work day, where an Employee is scheduled to work only 4 hours, it will only deduct 4 hours from the leave budget).

To save the expected working hours per day, it adds a new "Workplan" DocType to every Employee (under the "Attendance & Leaves" Tab). A workplan is a schedule of expected/regular working hours per day (e.g. a Workplan could look like "Monday 8 h, Tuesday 6h, Wednesday 8h, Thursday 4h, Friday 4h"). A workplan also has a start and an end date (because people typically might change their work load sometimes due to changing circumstances).

Whenever a workplan get's changed, the Leave Applications of that Employee get changed accordingly. That way the Application's Total Leave Days always match the hours set by the Employee's workplan set in that time frame. 

If an Employee's available Leave Balance for a Leave Application doesn't fully cover the last day of a leave period, but does cover a part of it, that part is set as a Fractional Leave Day. The date, weekday, hours and minutes still left to work that day are shown in the Leave Application in every step of creation/approval.


### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app workplan
```
